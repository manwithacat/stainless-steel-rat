# Copyright 2026 James Barlow
# SPDX-License-Identifier: Apache-2.0
"""Actual adjacent-table endpoints for arbitrary supported word widths."""
from . import supplied as M


def create(registers,width,words,slot):
    rows,angles=words.shape
    if not 1<=rows<=2048 or not 1<=width<=128 or not 0<=slot<(angles+4)//5:raise M.Refused('DIMENSION_OR_SLOT')
    selection=registers.get('selection',[]);ws=[registers.get('word_'+str(j),[]) for j in range(5)]
    brot=len(ws[0]);public=selection+sum(ws,[])
    if len(selection)!=(rows-1).bit_length() or not 1<=brot<=8 or any(len(w)!=brot for w in ws):raise M.Refused('REGISTER_WIDTH')
    if len(public)!=len(set(public)) or min(public)<0 or max(public)>=width:raise M.Refused('ALIASED_PUBLIC_REGISTERS')
    if any(int(v)<0 or int(v)>=1<<brot for row in words for v in row):raise M.Refused('WORD_OUTSIDE_WIDTH')
    values=[0]*width
    for j,q in enumerate(selection):
        v=M.address_truth(rows,1<<j);values[q]=v|(v<<rows)
    for j,w in enumerate(ws):
        for bit,q in enumerate(w):
            v=0
            for direction,group in enumerate((slot-1,slot)):
                col=5*group+j
                if 0<=col<angles:
                    for a in range(rows):v|=((int(words[a,col])>>bit)&1)<<(direction*rows+a)
            values[q]=v
    return M.Model(values,2*rows,0,dict(kind='actual_adjacent_word_endpoints',slot=slot,addresses=rows,
        word_width=brot,word_count=5,orientation_is_physical_wire=False,
        words_sha256=M.digest(words.tolist()),support='both actual adjacent endpoints and coherent span; not arbitrary words'))


def swapped(model,registers):
    expected=model.initial.copy();rows=model.rows//2;mask=(1<<rows)-1
    for j in range(5):
        for q in registers['word_'+str(j)]:expected[q]=((expected[q]&mask)<<rows)|(expected[q]>>rows)
    return expected
