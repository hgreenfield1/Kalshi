from setuptools import setup, find_packages

setup(
    name="kalshi-backtester",
    version="2.0.0",
    packages=find_packages(),
    install_requires=[
        "statsapi>=1.5.0",
        "requests>=2.28.0",
        "websockets>=10.0",
        "cryptography>=38.0.0",
        "python-dotenv>=0.19.0",
        "pandas>=1.5.0",
        "matplotlib>=3.6.0",
        "pytest>=7.0.0",
    ],
    python_requires=">=3.11",
)
