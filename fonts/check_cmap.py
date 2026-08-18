import struct, zlib, sys

data = open(sys.argv[1], 'rb').read()
sig = data[:4]

if sig == b'wOFF':
    # WOFF: header 44 bytes, entradas de 20 bytes, tablas posiblemente zlib
    _, _, _, numTables = struct.unpack('>4s4sIH', data[:14])
    tables = {}
    for i in range(numTables):
        tag, offset, clen, olen, csum = struct.unpack('>4sIIII', data[44 + i*20:64 + i*20])
        tables[tag] = (offset, clen, olen)

    def get_table(tag):
        off, clen, olen = tables[tag]
        raw = data[off:off+clen]
        return zlib.decompress(raw) if clen != olen else raw
else:
    # TTF/OTF: header 12 bytes, entradas de 16 bytes, sin compresión
    numTables = struct.unpack('>H', data[4:6])[0]
    tables = {}
    for i in range(numTables):
        tag, csum, offset, length = struct.unpack('>4sIII', data[12 + i*16:28 + i*16])
        tables[tag] = (offset, length, length)

    def get_table(tag):
        off, length, _ = tables[tag]
        return data[off:off+length]

print('formato:', sig, '| tablas:', numTables)
cmap = get_table(b'cmap')
version, nrecs = struct.unpack('>HH', cmap[:4])
recs = [struct.unpack('>HHI', cmap[4+i*8:12+i*8]) for i in range(nrecs)]
best = None
for pid, eid, off in recs:
    if pid in (3, 0):
        best = off
        break
if best is None:
    print('sin cmap utilizable')
    sys.exit()
sub = cmap[best:]
fmt, length, lang = struct.unpack('>HHH', sub[:6])
print('subtipo cmap:', fmt)
segs = {}
if fmt == 4:
    segX2 = struct.unpack('>H', sub[6:8])[0]
    nseg = segX2 // 2
    endCode = struct.unpack('>%dH' % nseg, sub[14:14+2*nseg])
    startCode = struct.unpack('>%dH' % nseg, sub[16+2*nseg:16+4*nseg])
    idDelta = struct.unpack('>%dh' % nseg, sub[16+4*nseg:16+6*nseg])
    for s, e, d in zip(startCode, endCode, idDelta):
        for cp in range(s, e+1):
            segs[cp] = (cp + d) & 0xFFFF
elif fmt == 12:
    ngroups = struct.unpack('>I', sub[12:16])[0]
    for i in range(ngroups):
        sc, ec, sg = struct.unpack('>III', sub[16+i*12:28+i*12])
        for cp in range(sc, ec+1):
            segs[cp] = sg + cp - sc

def has(cp):
    return cp in segs

for ch in ['A','Z','Á','É','Í','Ó','Ú','Ñ','á','é','í','ó','ú','ñ','¿','¡','ü','Ç','0','.',',','\'']:
    print(repr(ch), hex(ord(ch)), '->', 'SI' if has(ord(ch)) else 'NO')
