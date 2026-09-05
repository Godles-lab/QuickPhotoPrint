"""Numerical ICC interoperability and the export/manual-import user workflow."""
from dataclasses import asdict
from io import BytesIO
from itertools import product
import json
import random
import struct

from PIL import Image, ImageCms
import pytest
from ui_wait import wait_for_idle
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

import app
from core import SRGB, convert_output
from icc_edit import (ColorAdjustment, edited_profile, pack_profile, profile_bytes,
                      read_tags, save_adjusted_profile)


def pixels():
    rng = random.Random(27)
    values = [(v, v, v) for v in range(256)]
    values += [tuple(rng.randrange(256) for _ in range(3)) for _ in range(4000)]
    image = Image.new('RGB', (len(values), 1))
    image.putdata(values)
    return image


def transform(image, source, target, intent=1):
    return ImageCms.profileToProfile(image, source, target, outputMode='RGB',
                                    renderingIntent=intent, flags=ImageCms.Flags.NOOPTIMIZE)


def lut_fixture(kind, stage=0):
    """Small standard RGB/XYZ LUT profiles with distinct intent mappings."""
    base = SRGB.tobytes()
    tags = {k: v for k, v in read_tags(base).items()
            if k in (b'desc', b'cprt', b'wtpt', b'chad')}
    identity_matrix = struct.pack('>9i', 65536, 0, 0, 0, 65536, 0, 0, 0, 65536)

    def lut(reverse, gamma):
        if kind in (b'mft1', b'mft2'):
            depth = 1 if kind == b'mft1' else 2
            count, maximum, code = (256, 255, 'B') if depth == 1 else (4096, 65535, 'H')
            head = kind+bytes(4)+bytes((3, 3, 2, 0))+identity_matrix
            if depth == 2:
                head += struct.pack('>HH', count, count)
            # Nonidentity shapers catch incorrect curve composition order.
            inp = [round((i/(count-1))**gamma*maximum) for i in range(count)]*3
            clut = [int(v*maximum) for triple in product((0, 1), repeat=3) for v in triple]
            out = [round((i/(count-1))**(1/gamma)*maximum) for i in range(count)]*3
            return head+struct.pack(f'>{len(inp+clut+out)}{code}', *(inp+clut+out))
        # v4 mAB/mBA with B-only, matrix/M/B, or A/CLUT/B stages.
        head = bytearray((b'mAB ' if reverse else b'mBA ')+bytes(4)+bytes((3, 3))+bytes(22))
        curve = b'curv'+bytes(4)+struct.pack('>IH', 1, round(gamma*256))+bytes(2)
        identity = b'curv'+bytes(4)+struct.pack('>I', 0)
        blocks = {0: (curve if stage == 0 else identity)*3}
        if stage == 2:
            blocks[1] = identity_matrix+bytes(12)
            blocks[2] = curve*3
        elif stage == 4:
            clut = [int(v*65535) for triple in product((0, 1), repeat=3) for v in triple]
            blocks[3] = bytes((2, 2, 2))+bytes(13)+bytes((2, 0, 0, 0))+struct.pack('>24H', *clut)
            blocks[4] = curve*3
        for index, block in blocks.items():
            struct.pack_into('>I', head, 12+index*4, len(head))
            head.extend(block)
        return bytes(head)

    for intent in range(3):
        tags[f'B2A{intent}'.encode()] = lut(False, 1+intent*.2)
        tags[f'A2B{intent}'.encode()] = lut(True, 1+intent*.2)
    header = bytearray(base[:128])
    header[12:16] = b'prtr'
    if kind in (b'mft1', b'mft2'):
        header[8:12] = bytes((2, 0x40, 0, 0))
    return pack_profile(header, tags)


@pytest.mark.parametrize('kind,stage', [(b'mft1', 0), (b'mft2', 0), (b'mAB ', 0),
                                      (b'mAB ', 2), (b'mAB ', 4), (b'matrix', 0)])
def test_export_composes_forward_and_reverse_device_curves(kind, stage):
    data = SRGB.tobytes() if kind == b'matrix' else lut_fixture(kind, stage)
    adjustment = ColorAdjustment(brightness=20, contrast=15, red=-20, green=15, blue=-5)
    result = edited_profile(data, adjustment, '微调测试')
    source = ImageCms.getOpenProfile(BytesIO(data))
    target = ImageCms.getOpenProfile(BytesIO(result))
    image = pixels()
    for intent in range(4):
        expected = adjustment.apply(transform(image, SRGB, source, intent))
        actual = transform(image, SRGB, target, intent)
        errors = sorted(abs(a-b) for a, b in zip(actual.tobytes(), expected.tobytes()))
        assert errors[int(len(errors)*.99)] <= 1
        assert max(errors) <= (3 if kind == b'mft1' else 2)
        # Reverse comparison in Lab avoids huge RGB excursions near gamut edges.
        lab = ImageCms.createProfile('LAB')
        inverse = image.point([round(adjustment.inverse(i/255, ch)*255)
                               for ch in range(3) for i in range(256)])
        expected_lab = ImageCms.profileToProfile(inverse, source, lab, outputMode='LAB',
            renderingIntent=intent, flags=ImageCms.Flags.NOOPTIMIZE)
        actual_lab = ImageCms.profileToProfile(image, target, lab, outputMode='LAB',
            renderingIntent=intent, flags=ImageCms.Flags.NOOPTIMIZE)
        # Samples are quantized to RGB8 before the reference transform.
        errors = sorted(abs(a-b) for a,b in zip(actual_lab.tobytes(),expected_lab.tobytes()))
        assert errors[int(len(errors)*.99)] <= 2
    assert read_tags(result)[b'cprt'] == read_tags(data)[b'cprt']


def test_existing_brother_profile_keeps_clut_and_unmodified_paths(tmp_path):
    original = app.BUILTIN.read_bytes()
    tuning = ColorAdjustment(20, 15, -15, 10, 5)
    result = edited_profile(original, tuning, 'Brother Adjusted')
    old, new = read_tags(original), read_tags(result)
    for sig in (b'B2A0', b'A2B0', b'B2A1', b'A2B1', b'B2A2', b'A2B2'):
        start = 52+3*4096*2
        assert old[sig][start:-3*4096*2] == new[sig][start:-3*4096*2]
    image = pixels()
    profile = ImageCms.getOpenProfile(BytesIO(result))
    expected = tuning.apply(transform(image, SRGB, str(app.BUILTIN)))
    actual = transform(image, SRGB, profile)
    assert max(abs(a-b) for a,b in zip(actual.tobytes(),expected.tobytes())) <= 2
    neutral = edited_profile(original, ColorAdjustment(), 'Unchanged color')
    for sig, payload in old.items():
        if sig not in (b'desc', b'qpet'):
            assert read_tags(neutral)[sig] == payload
    assert app.BUILTIN.read_bytes() == original
    destination = tmp_path/'Brother-Adjusted.icc'
    destination.write_bytes(result)
    # Exercise the app's normal RGB8 path, including optimizer flag selection.
    live = convert_output(image, app.BUILTIN, adjustment=tuning)
    reimported = convert_output(image, destination)
    assert max(abs(a-b) for a,b in zip(live.tobytes(), reimported.tobytes())) <= 2


def test_neutral_extremes_and_invalid_parameters():
    image = pixels()
    assert ColorAdjustment().apply(image).tobytes() == image.tobytes()
    for values in product((-50, 50), repeat=3):
        adjustment = ColorAdjustment(values[0], values[1], values[2], -values[2], values[2])
        for ch in range(3):
            curve = adjustment.curves[ch]
            assert curve[0] == 0 and curve[-1] == 1
            assert all(a < b for a,b in zip(curve,curve[1:]))
            assert max(abs(adjustment.inverse(adjustment.value(x/255,ch),ch)-x/255)
                       for x in range(256)) < 1e-5
    for value in (float('nan'), 51, -51, True, '10'):
        with pytest.raises(ValueError):
            ColorAdjustment(red=value)
    # Driver-managed color must not silently apply an ICC adjustment.
    assert convert_output(image, adjustment=ColorAdjustment(red=25)).tobytes() == image.tobytes()


def test_export_failure_preserves_original_and_destination(tmp_path):
    source = tmp_path/'base.icc'
    source.write_bytes(SRGB.tobytes())
    before = source.read_bytes()
    with pytest.raises(ValueError, match='原始 ICC'):
        save_adjusted_profile(source, source, ColorAdjustment(red=10))
    assert source.read_bytes() == before
    target = tmp_path/'existing.icc'
    target.write_bytes(b'keep this file')
    broken = tmp_path/'broken.icc'
    broken.write_bytes(b'not an ICC')
    with pytest.raises(ValueError):
        save_adjusted_profile(broken, target, ColorAdjustment(red=10))
    assert target.read_bytes() == b'keep this file'
    tags = read_tags(before)
    tags[b'B2D0'] = b'mpet'+bytes(24)
    with pytest.raises(ValueError, match='浮点'):
        edited_profile(pack_profile(before[:128],tags),ColorAdjustment(red=10),'Unsupported')


def test_sliders_save_manual_import_reset_and_preset(qt, tmp_path, monkeypatch):
    w = app.Window()
    assert not w.tuning.isEnabled() and not w.tuning.adjustment().active
    w.profile.setCurrentIndex(w.profile.findData('srgb'))
    assert w.tuning.isEnabled()
    w.tuning.sliders['red'].setValue(-12)
    w.tuning.values['blue'].setValue(7)
    assert w.tuning.values['red'].value() == -12
    assert w.tuning.sliders['blue'].value() == 7
    adjustment = w.tuning.adjustment()
    w.save_preset()
    w.tuning.reset_button.click()
    assert not w.tuning.adjustment().active
    w.load_preset()
    assert w.tuning.adjustment() == adjustment
    selected, count = w.profile.selected_profile(), w.profile.count()
    path = tmp_path/'Saved.icc'
    monkeypatch.setattr(app.QFileDialog,'getSaveFileName',lambda *args: (str(path),''))
    w.tuning.save_button.click()
    assert path.is_file()
    assert w.profile.count() == count and w.profile.selected_profile() == selected
    assert w.tuning.adjustment() == adjustment
    assert json.loads(w.settings.value('importedProfiles','[]')) == []
    monkeypatch.setattr(app.QFileDialog,'getOpenFileName',lambda *args: (str(path),''))
    w.choose_icc()
    assert w.profile.selected_profile() == str(path)
    assert not w.tuning.adjustment().active  # Export already contains the correction.
    assert w.profile.count() == count+1
    # Cancel export leaves the current settings untouched.
    w.tuning.sliders['green'].setValue(8)
    monkeypatch.setattr(app.QFileDialog,'getSaveFileName',lambda *args: ('',''))
    w.save_edited_icc()
    assert w.tuning.adjustment().green == 8
    w.profile.setCurrentIndex(0)
    assert not w.tuning.isEnabled() and not w.tuning.adjustment().active
    w.close()


def test_icc_controls_never_transform_or_replace_preview(qt, monkeypatch):
    w = app.Window()
    w.source_photo = w.photo = Image.new('RGB', (80, 120), (128, 104, 80))
    w.canvas.set_photo(w.photo)
    original = w.photo.tobytes()
    cache_key = w.canvas.photo.cacheKey()
    calls = []

    def unexpected_processing(*args, **kwargs):
        calls.append(True)
        raise AssertionError('ICC control changes must not process preview pixels')

    monkeypatch.setattr(ImageCms, 'profileToProfile', unexpected_processing)
    monkeypatch.setattr(ColorAdjustment, 'apply', unexpected_processing)
    monkeypatch.setattr(w.canvas, 'set_photo', unexpected_processing)
    for profile in (str(app.BUILTIN), 'srgb', ''):
        w.profile.setCurrentIndex(w.profile.findData(profile))
        if profile:
            for i, slider in enumerate(w.tuning.sliders.values()):
                slider.setValue(35 if i % 2 else -25)
            w.intent.setCurrentIndex(1)
            w.bpc.setChecked(True)
            # Process pending events beyond the former 100 ms preview debounce.
            QTest.qWait(150)
            w.save_preset()
            w.tuning.reset_button.click()
            w.load_preset()
        qt.processEvents()
        assert w.canvas.photo.cacheKey() == cache_key
    QTest.qWait(150)
    assert calls == []
    assert w.photo.tobytes() == original
    assert w.canvas.photo.pixelColor(0,0).getRgb() == (128,104,80,255)
    w.close()


def test_load_and_rotate_keep_source_colors_with_active_icc_tuning(qt, tmp_path):
    w = app.Window()
    w.profile.setCurrentIndex(w.profile.findData('srgb'))
    w.tuning.set_adjustment(ColorAdjustment(green=40))
    original = Image.new('RGB', (80, 120), (128,104,80))
    original.putpixel((0,0), (40,80,140))
    path = tmp_path/'source.png'
    original.save(path)
    w.load(str(path))
    wait_for_idle(w)
    assert w.canvas.photo == app.qimage(original)
    w.rotate()
    assert w.canvas.photo == app.qimage(original.rotate(-90, expand=True))
    printed = convert_output(w.photo, 'srgb', adjustment=w.tuning.adjustment())
    assert printed.getpixel((0,0))[1] > w.photo.getpixel((0,0))[1]
    w.load(str(path))
    wait_for_idle(w)
    assert w.canvas.photo == app.qimage(original)
    w.tuning.reset_button.click()
    assert w.canvas.photo == app.qimage(original)
    w.close()


def test_slider_click_and_drag_update_values_without_processing_photo(qt):
    w = app.Window()
    w.tabs.setCurrentIndex(2)
    w.profile.setCurrentIndex(w.profile.findData(str(app.BUILTIN)))
    w.tuning_toggle.setChecked(True)
    w.source_photo = w.photo = Image.new('RGB', (80, 120), (128,104,80))
    w.canvas.set_photo(w.photo)
    cache_key = w.canvas.photo.cacheKey()
    w.show()
    qt.processEvents()
    slider = w.tuning.sliders['brightness']
    center = slider.rect().center()
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=center)
    QTest.mouseMove(slider, QPoint(slider.width()-8, center.y()))
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(slider.width()-8, center.y()))
    assert slider.value() > 0
    assert w.tuning.values['brightness'].value() == slider.value()
    before_click = slider.value()
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(8, center.y()))
    assert slider.value() < before_click
    assert w.tuning.values['brightness'].value() == slider.value()
    QTest.qWait(150)
    assert w.canvas.photo.cacheKey() == cache_key
    w.close()


def test_tuning_starts_collapsed_and_only_shows_requested_note(qt):
    w = app.Window()
    w.tabs.setCurrentIndex(2)
    w.profile.setCurrentIndex(w.profile.findData('srgb'))
    w.show()
    qt.processEvents()
    assert not w.tuning_toggle.isChecked() and w.tuning.isHidden()
    assert w.tuning_toggle.arrowType() == Qt.ArrowType.RightArrow
    page = w.tabs.widget(2).widget()
    notes = [label for label in page.findChildren(QLabel) if label.objectName() == 'muted']
    assert [label.text() for label in notes] == ['微调为打印后的颜色配置']
    assert not notes[0].isVisible()
    QTest.mouseClick(w.tuning_toggle, Qt.MouseButton.LeftButton)
    qt.processEvents()
    assert w.tuning.isVisible() and notes[0].isVisible()
    assert w.tuning_toggle.arrowType() == Qt.ArrowType.DownArrow
    w.tuning.sliders['green'].setValue(25)
    QTest.mouseClick(w.tuning_toggle, Qt.MouseButton.LeftButton)
    qt.processEvents()
    assert w.tuning.isHidden() and not notes[0].isVisible()
    assert w.tuning.adjustment().green == 25
    w.save_preset()
    w.close()
    restored = app.Window()
    assert restored.tuning.isHidden() and not restored.tuning_toggle.isChecked()
    assert restored.tuning.adjustment().green == 25
    restored.close()


def test_new_controls_ignore_mouse_wheel(qt):
    w = app.Window()
    w.profile.setCurrentIndex(w.profile.findData('srgb'))
    for widget in (*w.tuning.sliders.values(), *w.tuning.values.values()):
        event = QWheelEvent(QPointF(10,10), QPointF(10,10), QPoint(), QPoint(0,120),
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                           Qt.ScrollPhase.ScrollUpdate, False)
        qt.sendEvent(widget, event)
        assert widget.value() == 0
    w.close()
