#!/usr/bin/env python3
from pathlib import Path

from setuptools import find_namespace_packages, setup


ROOT = Path(__file__).resolve().parent

with (ROOT / "cli_anything" / "cad" / "README.md").open("r", encoding="utf-8") as fh:
    long_description = fh.read()


install_requires = [
    "build>=1.2.0",
    "setuptools>=68.0",
    "wheel>=0.43.0",
    "click>=8.1.0",
    "prompt-toolkit>=3.0.0",
    "fastapi>=0.115.0,<0.141.0",
    "starlette>=0.40.0,<1.0.0",
    "uvicorn[standard]>=0.30.0",
    "python-multipart>=0.0.9",
    "aiofiles>=24.1.0",
    "celery>=5.4.0",
    "redis>=5.0.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "ezdxf>=1.3.0",
    "pandas>=2.2.0",
    "openpyxl>=3.1.0",
    "requests>=2.31.0",
    "pydantic>=2.8.0",
    "pydantic-settings>=2.4.0",
    "structlog>=24.1.0",
    "python-dotenv>=1.0.1",
    "rich>=13.7.0",
    "psutil>=5.9.0",
    "python-jose[cryptography]>=3.3.0",
    "passlib[bcrypt]>=1.7.4",
    "pywin32>=306; platform_system == 'Windows'",
]


setup(
    name="cli-anything-cad",
    version="1.0.0",
    author="cli-anything contributors",
    description="CLI harness for local CAD translation workflows",
    long_description=long_description,
    long_description_content_type="text/markdown",
    python_requires=">=3.10",
    install_requires=install_requires,
    extras_require={
        "dev": [
        "pytest>=8.0.0",
        "pytest-asyncio>=0.23.0",
        "httpx>=0.27.0,<0.29.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "cli-anything-cad=cli_anything.cad.cad_cli:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
    package_dir={"": "."},
    packages=find_namespace_packages(
        include=["cli_anything", "cli_anything.cad", "cli_anything.cad.*"],
        exclude=["cli_anything.cad_legacy", "cli_anything.cad_legacy.*"],
    ),
)
