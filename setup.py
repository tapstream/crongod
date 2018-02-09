from setuptools import setup

from crongod import __version__

setup(
    name='crongod',
    version=__version__,
    url='http://github.com/tapstream/crongod',
    author='Nick Sitarz',
    author_email='nsitarz@gmail.com',
    maintainer='Nick Sitarz',
    maintainer_email='nsitarz@gmail.com',
    description=('A Python cron wrapper that features  '
                 'enforced timeouts and logstash integration.'),
    long_description=open('README.md').read(),
    license='MIT',
    packages=['crongod'],
    package_data={'crongod': ['crongod/error-template']},
    include_package_data=True,
    entry_points={'console_scripts': [
        'crongod = crongod.commands:supervise_single_task',
    ]},
    install_requires=['elasticsearch>=6.0.0,<7.0.0'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: MIT License',
        'Environment :: Console',
        'Intended Audience :: System Administrators',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 2.7',
        'Topic :: System :: Logging',
        'Topic :: System :: Systems Administration',
        'Topic :: Utilities',
    ],
)
