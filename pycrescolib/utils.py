"""
Utility functions for the Cresco library.
"""
import gzip
import io
import base64
import json
import logging
from zipfile import ZipFile
import hashlib
from typing import Dict, Any, Union, Optional, BinaryIO

# Setup logging
logger = logging.getLogger(__name__)

def compress_param(params: str) -> str:
    """Compress a string parameter.
    
    Args:
        params: String parameter to compress
        
    Returns:
        Base64 encoded compressed string
    """
    try:
        out = io.BytesIO()
        
        with gzip.GzipFile(fileobj=out, mode='w') as fo:
            fo.write(params.encode())
            
        bytes_obj = out.getvalue()
        return base64.b64encode(bytes_obj).decode('utf-8')
    except Exception as e:
        logger.error(f"Error compressing parameter: {e}")
        raise

def compress_data(byte_data: bytes) -> str:
    """Compress binary data.
    
    Args:
        byte_data: Binary data to compress
        
    Returns:
        Base64 encoded compressed data
    """
    try:
        out = io.BytesIO()
        
        with gzip.GzipFile(fileobj=out, mode='w') as fo:
            fo.write(byte_data)
            
        bytes_obj = out.getvalue()
        return base64.b64encode(bytes_obj).decode('utf-8')
    except Exception as e:
        logger.error(f"Error compressing data: {e}")
        raise

def encode_data(byte_data: bytes) -> str:
    """Encode binary data to base64.
    
    Args:
        byte_data: Binary data to encode
        
    Returns:
        Base64 encoded data
    """
    try:
        return base64.b64encode(byte_data).decode('utf-8')
    except Exception as e:
        logger.error(f"Error encoding data: {e}")
        raise

def decompress_param(param: str) -> str:
    """Decompress a base64 encoded compressed parameter.
    
    Args:
        param: Base64 encoded compressed parameter
        
    Returns:
        Decompressed string
    """
    try:
        compressed_bytes = base64.b64decode(param)
        uncompressed_bytes = gzip.decompress(compressed_bytes).decode()
        return uncompressed_bytes
    except Exception as e:
        logger.error(f"Error decompressing parameter: {e}")
        raise

def get_jar_info(jar_file_path: str) -> Dict[str, str]:
    """Get information from a JAR file.
    
    Args:
        jar_file_path: Path to JAR file
        
    Returns:
        Dictionary with plugin name, version, and MD5 hash
    """
    params = {}
    
    try:
        # Read manifest
        with ZipFile(jar_file_path, 'r') as myzip:
            try:
                myfile = myzip.read(name='META-INF/MANIFEST.MF')
                for line in myfile.decode().split('\n'):
                    line = line.strip().split(': ')
                    if len(line) == 2:
                        if line[0] == 'Bundle-SymbolicName':
                            params['pluginname'] = line[1]
                        if line[0] == 'Bundle-Version':
                            params['version'] = line[1]
            except KeyError:
                logger.error("META-INF/MANIFEST.MF not found in JAR file")
                raise ValueError("Invalid JAR file: Missing MANIFEST.MF")
        
        # Calculate MD5 hash
        with open(jar_file_path, 'rb') as f:
            params['md5'] = hashlib.md5(f.read()).hexdigest()
        
        # Validate required fields
        if 'pluginname' not in params:
            raise ValueError("Plugin name not found in MANIFEST.MF")
        if 'version' not in params:
            raise ValueError("Version not found in MANIFEST.MF")
            
        return params
    except Exception as e:
        logger.error(f"Error getting JAR info: {e}")
        raise

def json_serialize(obj: Any) -> str:
    """Serialize object to JSON with error handling.
    
    Args:
        obj: Object to serialize
        
    Returns:
        JSON string
    """
    try:
        return json.dumps(obj)
    except (TypeError, ValueError) as e:
        logger.error(f"Error serializing to JSON: {e}")
        raise

def json_deserialize(json_str: str) -> Any:
    """Deserialize JSON string with error handling.
    
    Args:
        json_str: JSON string to deserialize
        
    Returns:
        Deserialized object
    """
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Error deserializing JSON: {e}")
        raise

def read_file_bytes(file_path: str) -> bytes:
    """Read file as bytes with error handling.
    
    Args:
        file_path: Path to file
        
    Returns:
        File content as bytes
    """
    try:
        with open(file_path, "rb") as f:
            return f.read()
    except IOError as e:
        logger.error(f"Error reading file {file_path}: {e}")
        raise

def validate_ssl_config(verify: bool = False) -> None:
    """Configure SSL verification.
    
    Args:
        verify: Whether to verify SSL certificates
    """
    import ssl
    
    if not verify:
        try:
            # Create unverified context
            _unverified_context = ssl._create_unverified_context()
            
            # Apply globally
            ssl._create_default_https_context = lambda: _unverified_context
            
            logger.warning("SSL certificate verification disabled")
        except AttributeError:
            logger.warning("Could not configure SSL verification settings")
