e3-testsuite: User's Manual
===========================

``e3-testsuite`` is a Python library built on top of ``e3-core``. Its purpose
it to provide building blocks for software projects to create testsuites in a
simple way. This library is generic: for instance, the tested software does not
need to use Python.

Note that this manual assumes that readers are familiar with the Python
language (Python3, to be specific) and how to run scripts using its standard
interpreter CPython.

Installation
------------

``e3-testsuite`` is available on Pypi, so installing it is as simple as
running:

.. code-block:: sh

   pip install e3-testsuite


How to read this documentation
------------------------------

The :ref:`core_concepts` and :ref:`tutorial` sections are must read: the former
introduces notions required to understand most of the documentation and the
latter put them in practice, as a step-by-step guide to write a simple, but
real world testsuite.

From there, brave/curious readers can go on until the end of the documentation,
while readers with time/energy constraints can just go over the sections of
interest for their needs.


Topics
------

.. toctree::
   :maxdepth: 2

   core_concepts
   tutorial
   api_result
   api_test_driver
   api_classic
   api_diff
   api_control
   api_testsuite
   api_testcase_finder
   api_report
   adacore
   multiprocessing


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
