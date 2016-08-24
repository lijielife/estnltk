# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, absolute_import

import unittest

from ..text import Text
from ..syntax.parsers import MaltParser
from ..names import *


class MaltParserSupportTest(unittest.TestCase):

    def test_maltparser_sent1(self):
        mparser = MaltParser( )
        text = Text('Jänes oli parajasti põllu peal.')
        text.tag_analysis()
        text_parsed = mparser.parse_text(text, augment_words=True)
        text_labels = [ int(w[SYNTAX_LABEL]) for w in text_parsed.words ]
        text_heads  = [ int(w[SYNTAX_HEAD]) for w in text_parsed.words ]
        text_rels   = [ w[DEPREL] for w in text_parsed.words ]
        self.assertListEqual(text_labels, [1,2,3,4,5,6])
        self.assertListEqual(text_heads,  [2,0,2,5,2,5])
        self.assertListEqual(text_rels,   ['@SUBJ', 'ROOT', '@ADVL', '@P>', '@ADVL', 'xxx'])

    def test_maltparser_sent2(self):
        mparser = MaltParser( )
        text = Text('Suurt hunti nähes ta ehmus ja pani jooksu.')
        text.tag_analysis()
        text_parsed = mparser.parse_text(text, return_type="text", augment_words=True)
        text_labels = [ int(w[SYNTAX_LABEL]) for w in text_parsed.words ]
        text_heads  = [ int(w[SYNTAX_HEAD]) for w in text_parsed.words ]
        self.assertListEqual(text_labels, [1,2,3,4,5,6,7,8,9])
        self.assertListEqual(text_heads,  [2,3,0,3,3,7,3,7,8])

    def test_maltparser_sent3(self):
        mparser = MaltParser( )
        text = Text('Saksamaal Bonnis leidis aset kummaline juhtum murdvargaga, kes kutsus endale ise politsei.')
        text.tag_analysis()
        text_parsed = mparser.parse_text(text, return_type="text", augment_words=True)
        text_labels = [ int(w[SYNTAX_LABEL]) for w in text_parsed.words ]
        text_heads  = [ int(w[SYNTAX_HEAD]) for w in text_parsed.words ]
        self.assertListEqual(text_labels, [1,2,3,4,5,6,7,8,9,10,11,12,13,14])
        self.assertListEqual(text_heads,  [2,3,0,6,6,7,3,7,10,3,10,11,10,13])

        
    def test_maltparser_dep_graph1(self):
        mparser = MaltParser( )
        text = Text('Kohtusid suur hunt ja kuri lammas. Auhinnaks oli ilus valge tekk.')
        text.tag_analysis()
        dep_graphs = mparser.parse_text(text, return_type="dep_graphs", augment_words=True)
        
        treeStr = str(dep_graphs[0].tree()).strip()
        #self.assertEqual(treeStr, '(Kohtusid (hunt suur) (lammas ja kuri .))')
        self.assertEqual(treeStr, '(Kohtusid (hunt suur (lammas ja kuri .)))')
        
        treeStr = str(dep_graphs[1].tree()).strip()
        self.assertEqual(treeStr, '(oli Auhinnaks (tekk ilus valge .))')
