import json
from dataclasses import asdict

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QPushButton

import app
from core import Layout, SRGB, STANDARD_RGB, check_profile, convert_output
from profile_picker import CUSTOM_ROLE, IMPORT_PROFILE, StyledComboBox, delete_rect


def make_profile(tmp_path, name='自定义相纸'):
    path = tmp_path / f'{name}.icc'
    path.write_bytes(SRGB.tobytes())
    return path


def activate_import(window, qt):
    window.tabs.setCurrentIndex(2)
    window.show()
    qt.processEvents()
    window.profile.showPopup()
    qt.processEvents()
    view = window.profile.view()
    index = window.profile.model().index(window.profile.count() - 1, 0)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(index).center())
    qt.processEvents()


def test_profile_popup_opens_below_without_outer_frame(qt):
    w = app.Window()
    w.tabs.setCurrentIndex(2)
    w.show()
    qt.processEvents()
    w.profile.showPopup()
    qt.processEvents()
    popup = w.profile.view().window()
    visible_top = popup.geometry().top() + w.profile.view().geometry().top()
    combo_bottom = w.profile.mapToGlobal(w.profile.rect().bottomLeft()).y() + 1
    assert visible_top == combo_bottom
    assert popup.objectName() == 'comboPopupContainer'
    assert popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert popup.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert popup.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
    assert 'background-color: rgba(0,0,0,0)' in popup.styleSheet()
    w.profile.hidePopup()
    w.close()


def test_every_app_combo_uses_the_same_downward_rounded_popup(qt):
    w = app.Window()
    w.show()
    qt.processEvents()
    combos = w.findChildren(QComboBox)
    assert combos and all(isinstance(combo, StyledComboBox) for combo in combos)
    for combo in combos:
        if not combo.isVisible() or not combo.count():
            continue
        combo.showPopup()
        qt.processEvents()
        popup = combo.view().window()
        visible_top = popup.geometry().top() + combo.view().geometry().top()
        combo_bottom = combo.mapToGlobal(combo.rect().bottomLeft()).y() + 1
        assert visible_top == combo_bottom
        assert popup.grab().toImage().pixelColor(0, 0).alpha() == 0
        combo.hidePopup()
    w.close()


def test_profile_defaults_and_standard_rgb(qt):
    w = app.Window()
    assert [w.profile.itemText(i) for i in range(w.profile.count())] == [
        '由打印机管理颜色', '普通RGB配置', 'Brother·柯达·高光', '导入其他配置文件...']
    assert w.profile.selected_profile() == ''
    assert not w.intent.isEnabled() and not w.bpc.isEnabled()
    assert not any('选择其他 ICC' in b.text() for b in w.findChildren(QPushButton))
    w.profile.setCurrentIndex(w.profile.findData(STANDARD_RGB))
    assert w.intent.isEnabled() and w.bpc.isEnabled()
    assert 'sRGB' in check_profile(w.profile.selected_profile())
    image = Image.new('RGB', (3, 1))
    image.putdata([(255, 0, 0), (128, 128, 128), (12, 80, 210)])
    for intent in range(4):
        for bpc in (False, True):
            assert convert_output(image, w.profile.selected_profile(), intent, bpc).tobytes() == image.tobytes()
    w.close()


@pytest.mark.parametrize('saved,expected', [('', ''), ('builtin', str(app.BUILTIN)), (STANDARD_RGB, STANDARD_RGB)])
def test_saved_profile_restores_by_value_after_reordering(qt, saved, expected):
    settings = app.QSettings('Godles-lab', 'QuickPhotoPrintLocal')
    settings.setValue('printerManagedDefaultApplied', True)
    settings.setValue('preset', json.dumps({'layout': asdict(Layout()), 'profile': saved}))
    w = app.Window()
    assert w.profile.selected_profile() == expected
    w.close()


def test_legacy_implicit_default_still_migrates_once(qt):
    settings = app.QSettings('Godles-lab', 'QuickPhotoPrintLocal')
    settings.setValue('preset', json.dumps({'layout': asdict(Layout()), 'profile': 'builtin'}))
    w = app.Window()
    assert w.profile.selected_profile() == ''
    w.profile.setCurrentIndex(w.profile.findData(str(app.BUILTIN)))
    w.save_preset()
    w.close()
    restored = app.Window()
    assert restored.profile.selected_profile() == str(app.BUILTIN)
    restored.close()


def test_import_action_cancel_error_dedup_and_persistence(qt, tmp_path, monkeypatch):
    w = app.Window()
    w.profile.setCurrentIndex(w.profile.findData(STANDARD_RGB))
    monkeypatch.setattr(app.QFileDialog, 'getOpenFileName', lambda *args: ('', ''))
    activate_import(w, qt)
    assert w.profile.selected_profile() == STANDARD_RGB
    assert w.profile.currentData() == STANDARD_RGB

    invalid = tmp_path / 'invalid.icc'
    invalid.write_bytes(b'not a profile')
    errors = []
    monkeypatch.setattr(w, 'error', errors.append)
    monkeypatch.setattr(app.QFileDialog, 'getOpenFileName', lambda *args: (str(invalid), ''))
    activate_import(w, qt)
    assert errors and w.profile.count() == 4
    assert w.profile.selected_profile() == STANDARD_RGB

    path = make_profile(tmp_path)
    monkeypatch.setattr(app.QFileDialog, 'getOpenFileName', lambda *args: (str(path), ''))
    activate_import(w, qt)
    activate_import(w, qt)
    assert w.profile.count() == 5
    assert w.profile.selected_profile() == str(path)
    assert w.profile.itemData(3, CUSTOM_ROLE)
    assert w.profile.itemData(4) == IMPORT_PROFILE
    w.save_preset()
    w.close()
    restored = app.Window()
    assert restored.profile.count() == 5
    assert restored.profile.selected_profile() == str(path)
    restored.close()


def test_delete_imported_profile_preserves_file_and_clears_saved_reference(qt, tmp_path):
    path = make_profile(tmp_path)
    w = app.Window()
    w.profile.setCurrentIndex(w.add_imported_profile(str(path), check_profile(path)))
    w.preview_scale.setValue(99)
    w.save_preset()
    w.tabs.setCurrentIndex(2)
    w.show()
    qt.processEvents()
    w.profile.showPopup()
    qt.processEvents()
    view = w.profile.view()
    index = w.profile.model().index(w.profile.findData(str(path)), 0)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=delete_rect(view.visualRect(index)).center())
    qt.processEvents()
    assert path.exists()
    assert w.profile.findData(str(path)) == -1
    assert w.profile.selected_profile() == ''
    assert not w.intent.isEnabled()
    saved = json.loads(w.settings.value('preset'))
    assert saved['profile'] == '' and saved['preview_scale'] == 99
    assert json.loads(w.settings.value('importedProfiles')) == []
    w.profile.hidePopup()
    w.close()
    restored = app.Window()
    assert restored.profile.count() == 4
    assert restored.profile.selected_profile() == ''
    restored.close()


def test_remove_unselected_profile_and_protect_builtins(qt, tmp_path):
    w = app.Window()
    path = make_profile(tmp_path)
    w.add_imported_profile(str(path), check_profile(path))
    w.profile.setCurrentIndex(w.profile.findData(STANDARD_RGB))
    w.tabs.setCurrentIndex(2)
    w.show()
    qt.processEvents()
    w.profile.showPopup()
    qt.processEvents()
    view = w.profile.view()
    view.setCurrentIndex(w.profile.model().index(w.profile.findData(str(path)), 0))
    QTest.keyClick(view, Qt.Key.Key_Delete)
    for value in ('', STANDARD_RGB, str(app.BUILTIN), IMPORT_PROFILE):
        w.remove_imported_profile(value)
    assert w.profile.count() == 4
    assert w.profile.selected_profile() == STANDARD_RGB
    assert path.exists()
    w.profile.hidePopup()
    w.close()
