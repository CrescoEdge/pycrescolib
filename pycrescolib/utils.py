import gzip
import io
import base64
from zipfile import ZipFile
import hashlib

def compress_param(params):
    out = io.BytesIO()

    with gzip.GzipFile(fileobj=out, mode='w') as fo:
        fo.write(params.encode())

    bytes_obj = out.getvalue()
    return base64.b64encode(bytes_obj).decode('utf-8')

def compress_data(byte_data):
    out = io.BytesIO()

    with gzip.GzipFile(fileobj=out, mode='w') as fo:
        fo.write(byte_data)

    bytes_obj = out.getvalue()
    return base64.b64encode(bytes_obj).decode('utf-8')

def encode_data(byte_data):

    return base64.b64encode(byte_data).decode('utf-8')


def decompress_param(param):
    compressed_bytes = base64.b64decode(param)
    uncompressed_bytes = gzip.decompress(compressed_bytes).decode()
    return uncompressed_bytes

def get_jar_info(jar_file_path):

    params = dict()

    with ZipFile(jar_file_path, 'r') as myzip:
        myfile = myzip.read(name='META-INF/MANIFEST.MF')
        for line in myfile.decode().split('\n'):
            line = line.strip().split(': ')
            if line[0] == 'Bundle-SymbolicName':
                params['pluginname'] = line[1]
            if line[0] == 'Bundle-Version':
                params['version'] = line[1]

    params['md5'] = hashlib.md5(open(jar_file_path, 'rb').read()).hexdigest()

    return params