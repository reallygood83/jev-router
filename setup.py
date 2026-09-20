from setuptools import find_packages, setup


setup(
    name="jev-router",
    version="0.1.0",
    description="A thin Jev router for approved, healthy local AI models",
    packages=find_packages("src"),
    package_dir={"": "src"},
    python_requires=">=3.9",
    entry_points={"console_scripts": ["jev-router=jev_router.cli:main"]},
)
