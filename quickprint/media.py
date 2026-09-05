"""macOS CUPS job options. Read capabilities; never modify global defaults."""
import subprocess
import sys
from dataclasses import dataclass

LABELS={'any':'自动选择','com.brother-bp71':'Brother BP71','photographic-glossy':'光面相纸',
        'stationery':'普通纸张','stationery-inkjet':'喷墨打印纸','photographic-matte':'哑光相纸'}
QUALITY={'Draft':'草稿','Normal':'标准','High':'高质量'}


def parse_options(text):
    result={}
    for line in text.splitlines():
        if ': ' not in line: continue
        header,choices=line.split(': ',1)
        result[header.split('/',1)[0]]=[v.lstrip('*') for v in choices.split()]
    return result


def capabilities(printer):
    if sys.platform!='darwin' or not printer: return {}
    result=subprocess.run(['/usr/bin/lpoptions','-p',printer,'-l'],capture_output=True,text=True,timeout=8)
    if result.returncode: return {}
    return parse_options(result.stdout)


def job_arguments(printer,paper,media,quality,copies,options):
    if media not in options.get('MediaType',[]): raise ValueError('驱动不支持所选纸张类型，请刷新打印机。')
    if paper not in options.get('PageSize',[]): raise ValueError('直接打印需要驱动支持的纸张规格；自定义尺寸请用系统打印窗口。')
    if quality not in options.get('cupsPrintQuality',[]): raise ValueError('驱动不支持所选质量，请刷新打印机。')
    if not 1<=copies<=99: raise ValueError('份数需在 1–99。')
    return ['/usr/bin/lp','-d',printer,'-t','Quick Photo Print','-n',str(copies),
            '-o',f'PageSize={paper}','-o',f'MediaType={media}','-o',f'cupsPrintQuality={quality}',
            '-o','sides=one-sided','-o','print-scaling=none','-o','fit-to-page=false',
            '-o','number-up=1','-o','ColorModel=RGB','-']


def submit_pdf(arguments,data):
    # lp reads the entire PDF from stdin before returning; no photo filename sent.
    result=subprocess.run(arguments,input=data,capture_output=True,timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace').strip() or '系统打印队列拒绝了任务。')
    return result.stdout.decode(errors='replace').strip()
