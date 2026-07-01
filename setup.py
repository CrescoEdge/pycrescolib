from setuptools import setup

setup(
    name='pycrescolib',
    version='1.3.0',
    packages=['pycrescolib'],
    url='http://cresco.io',
    license='Apache 2.0',
    author='Cresco Team',
    author_email='info@cresco.io',
    description='Python Cresco Client Library',
    python_requires='>=3.8',
    install_requires=['websockets>=10.0', 'cryptography>=36.0.0', 'backoff>=2.0.0'],

)
