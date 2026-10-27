"""PNG completeness follows IHDR scanline layout, not Pillow's padded output."""
from importlib import import_module
from io import BytesIO
import struct
import zlib

from PIL import Image
import pytest

assets=import_module('experiments.novel-to-game.game_assets')


def encoded_png(width,height,depth,color,streams,interlace=0):
    def chunk(kind,content):
        return struct.pack('>I',len(content))+kind+content+struct.pack('>I',zlib.crc32(kind+content))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,depth,color,0,0,interlace))
        +b''.join(chunk(b'IDAT',stream) for stream in streams)+chunk(b'IEND',b''))


@pytest.mark.parametrize('mode,bits',[
    ('1',None),('L',None),('LA',None),('RGB',None),('RGBA',None),('I;16',None),
    ('P',1),('P',2),('P',4),('P',8)])
def test_complete_packed_and_multichannel_pngs_are_accepted(tmp_path,mode,bits):
    image=Image.new(mode,(13,9))
    if mode=='P':image.putpalette(list(range(256))*3)
    path=tmp_path/'complete.png';image.save(path,**({'bits':bits} if bits else {}))
    assert assets.png_info(path,dict(columns=1,rows=1))==dict(width=13,height=9,cell_width=13,cell_height=9)


@pytest.mark.parametrize('color,sample',[(2,bytes.fromhex('11117777aaaa')),(6,bytes.fromhex('11117777aaaaffff'))])
def test_complete_16_bit_truecolour_streams_are_accepted(tmp_path,color,sample):
    path=tmp_path/'sixteen.png';path.write_bytes(encoded_png(9,9,16,color,[zlib.compress((b'\x00'+sample*9)*9)]))
    assert assets.png_info(path,dict(columns=1,rows=1))['width']==9


@pytest.mark.parametrize('size,pass_shapes',[(1,[(1,1)]),(9,[(2,2),(1,2),(3,1),(2,3),(5,2),(4,5),(9,4)])])
def test_complete_adam7_passes_are_accepted(tmp_path,size,pass_shapes):
    pixel=bytes((81,119,105,255))
    raw=b''.join((b'\x00'+pixel*columns)*rows for columns,rows in pass_shapes)
    data=encoded_png(size,size,8,6,[zlib.compress(raw)],interlace=1)
    with Image.open(BytesIO(data)) as image:
        image.load();assert set(image.getdata())=={(81,119,105,255)}
    path=tmp_path/'interlaced.png';path.write_bytes(data)
    assert assets.png_info(path,dict(columns=1,rows=1))['height']==size


def test_complete_stream_can_span_multiple_idat_chunks(tmp_path):
    stream=zlib.compress((b'\x00'+bytes((81,119,105,255))*3)*2)
    path=tmp_path/'split.png';path.write_bytes(encoded_png(3,2,8,6,[stream[:1],stream[1:-2],stream[-2:]]))
    assert assets.png_info(path,dict(columns=1,rows=1))['height']==2


@pytest.mark.parametrize('fault',['short','long','unfinished','trailing'])
def test_scanline_count_and_zlib_termination_are_exact(tmp_path,fault):
    row=b'\x00'+bytes((81,119,105,255))*3
    stream=zlib.compress(row*({'short':1,'long':3}.get(fault,2)))
    if fault=='unfinished':stream=stream[:-1]
    if fault=='trailing':stream+=b'unexpected trailing stream data'
    path=tmp_path/'bad.png';path.write_bytes(encoded_png(3,2,8,6,[stream]))
    with pytest.raises(OSError,match='scanlines'):assets.png_info(path,dict(columns=1,rows=1))


def test_animated_png_is_rejected_by_the_static_background_contract(tmp_path):
    path=tmp_path/'animated.png'
    Image.new('RGBA',(13,9),'green').save(path,save_all=True,append_images=[Image.new('RGBA',(13,9),'blue')])
    with pytest.raises(OSError,match='static PNG'):assets.png_info(path,dict(columns=1,rows=1))
