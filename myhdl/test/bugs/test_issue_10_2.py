#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Failed VHDL code example
"""
import myhdl
from myhdl import *

def unsigned(width, value=0, cls=intbv):
    """Create an unsigned signal based on a bitvector with the
    specified width and initial value.
    """
    return Signal(cls(value, 0, 2**width))

def signed(width, value=0, cls=intbv):
    """Create an signed signal based on a bitvector with the
    specified width and initial value.
    """
    return Signal(cls(value, -2**(width-1), 2**(width-1)))


flags = unsigned(4)
position = signed(28)

@block
def Logic(flags, position):

    conc = unsigned(32)

    @instance
    def doit():
        flags.next = 4 
        position.next = 28
        yield delay(10)
        conc.next = concat(flags, position)
        yield delay(10)
        print(conc) 
    return doit

def test_issue_10_2():
    assert Logic(flags, position).verify_convert() == 0
