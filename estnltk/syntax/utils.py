# -*- coding: utf-8 -*- 
#
#   An unified interface for Estonian syntactic parsers;
#   
#   Aims to support:
#    *) VISL-CG3 based syntactic analysis;
#    *) MaltParser based syntactic analysis;
#

from __future__ import unicode_literals, print_function

import re, json
import os, os.path
import codecs, sys

#from nltk.tokenize.regexp import WhitespaceTokenizer
from nltk.tokenize.simple import LineTokenizer
from nltk.tokenize.regexp import RegexpTokenizer

from estnltk.names import *
from estnltk.text  import Text

from estnltk.maltparser_support import MaltParser, align_CONLL_with_Text
from syntax_preprocessing import SyntaxPreprocessing
from vislcg3_syntax import VISLCG3Pipeline, cleanup_lines, align_cg3_with_Text



# ==================================================================================
# ==================================================================================
#   Normalising  dependency syntactic information in the alignments
# ==================================================================================
# ==================================================================================

pat_cg3_surface_rel = re.compile('(@\S+)')
pat_cg3_dep_rel     = re.compile('#(\d+)\s*->\s*(\d+)')

def normalise_alignments( alignments, type='VISLCG3', **kwargs ):
    ''' Normalises dependency syntactic information in the given list of alignments.
        *) Translates tree node indices from the syntax format (indices starting 
           from 1), to EstNLTK format (indices starting from 0);
        *) Removes redundant information (morphological analyses) and keeps only 
           syntactic information, in the most compact format;
        *) Brings MaltParser and VISLCG3 info into common format;
        
        Expects that the list of alignments contains dicts, where each dict has 
        following attributes (at minimum):
          'start'   -- start index of the word in Text;
          'end'     -- end index of the word in Text;
          'sent_id' -- index of the sentence in Text, starting from 0;
          'parser_out' -- list of analyses from the output of the syntactic parser;
        Assumes that dicts are listed in the order of words appearance in the text;
        ( basically, assumes the output of methods align_CONLL_with_Text() and 
          align_cg3_with_Text() )
        
        Returns the input list (alignments), where old analysis lines ('parser_out') have 
        been replaced with the new compact form of analyses (if keep_old == False), or where 
        old analysis lines ('parser_out') have been replaced the new compact form of analyses,
        and the old analysis lines are preserved under a separate key: 'init_parser_out' (if 
        keep_old == True);

        In the compact list of analyses, each item has the following structure:
           [ syntactic_label, index_of_the_head ]
         *) syntactic_label
                surface syntactic label of the word, e.g. '@SUBJ', '@OBJ', '@ADVL'
         *) index_of_the_head
                index of the head; -1 if the current token is root;


        Parameters
        -----------
        alignments : list of items
            A list of dicts, where each item/dict has following attributes:
            'start', 'end', 'sent_id', 'parser_out'

        type : str
            Type of data in list_of_analysis_lines; Possible types: 'VISLCG3'
            (default), and 'CONLL';

        rep_miss_w_dummy : bool
            Optional argument specifying whether missing analyses should be replaced
            with dummy analyses ( in the form ['xxx', link_to_self] ); If False,
            an Exception is raised in case of a missing analysis;
            Default:True
            
        fix_selfrefs : bool
            Optional argument specifying  whether  self-references  in  syntactic 
            dependencies should be fixed;
            A self-reference link is firstly re-oriented as a link to the previous word
            in the sentence, and if the previous word does  not  exist,  the  link  is 
            re-oriented to the next word in the sentence; If the self-linked word is
            the only word in the sentence, it is made the root of the sentence;
            Default:True
        
        keep_old : bool
            Optional argument specifying  whether the old analysis lines should be 
            preserved after overwriting 'parser_out' with new analysis lines;
            If True, each dict will be augmented with key 'init_parser_out' which
            contains the initial/old analysis lines;
            Default:False
        
        mark_root : bool
            Optional argument specifying whether the root node in the dependency tree 
            (the node pointing to -1) should be assigned the label 'ROOT' (regardless
            its current label).
            This might be required, if one wants to make MaltParser's and VISLCG3 out-
            puts more similar, as MaltParser currently uses 'ROOT' labels, while VISLCG3 
            does not;
            Default:False


        (Example text: 'Millega pitsat tellida ? Hea küsimus .')
        Example input (VISLC3):
        -----------------------
        {'end': 7, 'sent_id': 0, 'start': 0, 'parser_out': ['\t"mis" Lga P inter rel sg kom @NN> @ADVL #1->3\r']}
        {'end': 14, 'sent_id': 0, 'start': 8, 'parser_out': ['\t"pitsa" Lt S com sg part @OBJ #2->3\r']}
        {'end': 22, 'sent_id': 0, 'start': 15, 'parser_out': ['\t"telli" Lda V main inf @IMV #3->0\r']}
        {'end': 23, 'sent_id': 0, 'start': 22, 'parser_out': ['\t"?" Z Int CLB #4->4\r']}
        {'end': 27, 'sent_id': 1, 'start': 24, 'parser_out': ['\t"hea" L0 A pos sg nom @AN> #1->2\r']}
        {'end': 35, 'sent_id': 1, 'start': 28, 'parser_out': ['\t"küsimus" L0 S com sg nom @SUBJ #2->0\r']}
        {'end': 36, 'sent_id': 1, 'start': 35, 'parser_out': ['\t"." Z Fst CLB #3->3\r']}

        Example output:
        ---------------
        {'sent_id': 0, 'start': 0, 'end': 7, 'parser_out': [['@NN>', 2], ['@ADVL', 2]]}
        {'sent_id': 0, 'start': 8, 'end': 14, 'parser_out': [['@OBJ', 2]]}
        {'sent_id': 0, 'start': 15, 'end': 22, 'parser_out': [['@IMV', -1]]}
        {'sent_id': 0, 'start': 22, 'end': 23, 'parser_out': [['xxx', 2]]}
        {'sent_id': 1, 'start': 24, 'end': 27, 'parser_out': [['@AN>', 1]]}
        {'sent_id': 1, 'start': 28, 'end': 35, 'parser_out': [['@SUBJ', -1]]}
        {'sent_id': 1, 'start': 35, 'end': 36, 'parser_out': [['xxx', 1]]}

    '''
    if not isinstance( alignments, list ):
        raise Exception('(!) Unexpected type of input argument! Expected a list of strings.')
    if type.lower() in ['vislcg3','cg3']:
       type = 1
    elif type.lower() in ['conll', 'malt', 'maltparser']:
       type = 2
    else: 
       raise Exception('(!) Unexpected type of data: ', type)
    keep_old         = False
    rep_miss_w_dummy = True
    mark_root        = False
    fix_selfrefs     = True
    for argName, argVal in kwargs.items():
        if argName in ['selfrefs', 'fix_selfrefs'] and argVal in [True, False]:
           #  Fix self-references
           fix_selfrefs = argVal
        if argName in ['keep_old'] and argVal in [True, False]:
           #  After the normalisation, keep also the original analyses;
           keep_old = argVal
        if argName in ['rep_miss_w_dummy', 'rep_miss'] and argVal in [True, False]:
           #  Replace missing analyses with dummy analyses;
           rep_miss_w_dummy = argVal
        if argName in ['mark_root', 'root'] and argVal in [True, False]:
           #  Mark the root node in the syntactic tree with the label ROOT;
           mark_root = argVal
    # Iterate over the alignments and normalise information
    prev_sent_id = -1
    wordID = 0
    for i in range(len(alignments)):
        alignment = alignments[i]
        if prev_sent_id != alignment['sent_id']:
            # Start of a new sentence: reset word id
            wordID = 0
        # 1) Extract syntactic information
        foundRelations = []
        if type == 1:
            # *****************  VISLCG3 format
            for line in alignment['parser_out']:
                # Extract info from VISLCG3 format analysis:
                sfuncs  = pat_cg3_surface_rel.findall( line )
                deprels = pat_cg3_dep_rel.findall( line )
                # If sfuncs is empty, generate an empty syntactic function (e.g. for 
                # punctuation)
                sfuncs = ['xxx'] if not sfuncs else sfuncs
                # Generate all pairs of labels vs dependency
                for func in sfuncs:
                    for (relS,relT) in deprels:
                        relS = int(relS)-1
                        relT = int(relT)-1
                        foundRelations.append( [func, relT] )
        elif type == 2:
            # *****************  CONLL format
            for line in alignment['parser_out']:
                parts = line.split('\t')
                if len(parts) != 10:
                    raise Exception('(!) Unexpected line format for CONLL data:', line)
                relT = int( parts[6] ) - 1
                func = parts[7]
                foundRelations.append( [func, relT] )
        # Handle missing relations (VISLCG3 specific problem)
        if not foundRelations:
            # If no alignments were found (probably due to an error in analysis)
            if rep_miss_w_dummy:
                # Replace missing analysis with a dummy analysis, with dep link 
                # pointing to self;
                foundRelations.append( ['xxx', wordID] )
            else:
                raise Exception('(!) Analysis missing for the word nr.', alignment[0])
        # Fix self references ( if requested )
        if fix_selfrefs:
            for r in range(len(foundRelations)):
                if foundRelations[r][1] == wordID:
                    # Make it to point to the previous word in the sentence,
                    # and if the previous one does not exist, make it to point
                    # to the next word;
                    foundRelations[r][1] = \
                        wordID-1 if wordID-1 > -1 else wordID+1
                    # If the self-linked token is the only token in the sentence, 
                    # mark it as the root of the sentence:
                    if wordID-1 == -1 and (i+1 == len(alignments) or \
                       alignments[i]['sent_id'] != alignments[i+1]['sent_id']):
                        foundRelations[r][1] = -1
        # Mark the root node in the syntactic tree with the label ROOT ( if requested )
        if mark_root:
            for r in range(len(foundRelations)):
                if foundRelations[r][1] == -1:
                    foundRelations[r][0] = 'ROOT'
        # 2) Replace existing syntactic info with more compact info
        if not keep_old:
            # Overwrite old info
            alignment['parser_out'] = foundRelations
        else: 
            # or preserve the initial information, and add new compact information
            alignment['init_parser_out'] = alignment['parser_out']
            alignment['parser_out']      = foundRelations
        alignments[i] = alignment
        prev_sent_id = alignment['sent_id']
        # Increase word id 
        wordID += 1
    return alignments


# ==================================================================================
# ==================================================================================
#   Importing  syntactically parsed text from file
# ==================================================================================
# ==================================================================================

pat_double_quoted  = re.compile('^".*"$')
pat_cg3_word_token = re.compile('^"<(.+)>"$')

def read_text_from_cg3_file( file_name, layer_name='vislcg3_syntax', **kwargs ):
    ''' Reads the output of VISLCG3 syntactic analysis from given file, and 
        returns as a Text object.
        
        The Text object has been tokenized for paragraphs, sentences, words, and it 
        contains syntactic analyses aligned with word spans, in the layer *layer_name* 
        (by default: 'vislcg3_syntax');
        
        Attached syntactic analyses are in the format as is the output of 
          utils.normalise_alignments();
        
        Parameters
        -----------
        file_name : str
            Name of the input file; Should contain syntactically analysed text,
            following the format of the output of VISLCG3 syntactic analyser;
        
        clean_up : bool
            Optional argument specifying whether the vislcg3_syntax.cleanup_lines()
            should be applied in the lines of syntactic analyses read from the 
            file;
            Default: False
        
        layer_name : str
            Name of the Text's layer in which syntactic analyses are stored; 
            Defaults to 'vislcg3_syntax';
        
            For other parameters, see optional parameters of the methods:
            
             utils.normalise_alignments():          "rep_miss_w_dummy", "fix_selfrefs",
                                                    "keep_old", "mark_root";
             vislcg3_syntax.align_cg3_with_Text():  "check_tokens", "add_word_ids";
             vislcg3_syntax.cleanup_lines():        "remove_caps", "remove_clo",
                                                    "double_quotes";
        
        
    '''
    clean_up = False
    for argName, argVal in kwargs.items():
        if argName in ['clean_up', 'cleanup'] and argVal in [True, False]:
           #  Clean up lines
           clean_up = argVal
    # 1) Load vislcg3 analysed text from file
    cg3_lines = []
    in_f = codecs.open(file_name, mode='r', encoding='utf-8')
    for line in in_f:
        cg3_lines.append( line.rstrip() )
    in_f.close()
    # Clean up lines of syntactic analyses (if requested)
    if clean_up:
        cg3_lines = cleanup_lines( cg3_lines, **kwargs )

    # 2) Extract sentences and word tokens
    sentences = []
    sentence  = []
    for i, line in enumerate( cg3_lines ):
        if line == '"<s>"':
            if sentence:
                print('(!) Sentence begins before previous ends at line: '+str(i), \
                      file=sys.stderr)
            sentence  = []
        elif pat_double_quoted.match( line ) and line != '"<s>"' and line != '"</s>"':
            token_match = pat_cg3_word_token.match( line )
            if token_match:
                line = token_match.group(1)
            else:
                raise Exception('(!) Unexpected token format: ', line)
            sentence.append( line )
        elif line == '"</s>"':
            if not sentence:
                print('(!) Empty sentence at line: '+str(i), \
                      file=sys.stderr)
            # (!) Use double space instead of single space in order to distinguish
            #     word-tokenizing space from the single space in the multiwords
            #     (e.g. 'Rio de Janeiro' as a single word);
            sentences.append( '  '.join(sentence) )
            sentence = []

    # 3) Construct the estnltk's Text
    kwargs4text = {
      # Use custom tokenization utils in order to preserve exactly the same 
      # tokenization as was in the input;
      "word_tokenizer": RegexpTokenizer("  ", gaps=True),
      "sentence_tokenizer": LineTokenizer()
    }
    text = Text( '\n'.join(sentences), **kwargs4text )
    # Tokenize up to the words layer
    text.tokenize_words()
    
    # 4) Align syntactic analyses with the Text
    alignments = align_cg3_with_Text( cg3_lines, text, **kwargs )
    normalise_alignments( alignments, type='VISLCG3', **kwargs )
    # Attach alignments to the text
    text[ layer_name ] = alignments
    return text


def read_text_from_conll_file( file_name, layer_name='conll_syntax', **kwargs ):
    ''' Reads the CONLL format syntactic analysis from given file, and returns as 
        a Text object.
        
        The Text object has been tokenized for paragraphs, sentences, words, and it 
        contains syntactic analyses aligned with word spans, in the layer *layer_name* 
        (by default: 'conll_syntax');
        
        Attached syntactic analyses are in the format as is the output of 
          utils.normalise_alignments();
        
        Parameters
        -----------
        file_name : str
            Name of the input file; Should contain syntactically analysed text,
            following the CONLL format;
        
        layer_name : str
            Name of the Text's layer in which syntactic analyses are stored; 
            Defaults to 'conll_syntax';
        
            For other parameters, see optional parameters of the methods:
            
             utils.normalise_alignments():          "rep_miss_w_dummy", "fix_selfrefs",
                                                    "keep_old", "mark_root";
             maltparser_support.align_CONLL_with_Text():  "check_tokens", "add_word_ids";

    '''
    # 1) Load conll analysed text from file
    conll_lines = []
    in_f = codecs.open(file_name, mode='r', encoding='utf-8')
    for line in in_f:
        conll_lines.append( line.rstrip() )
    in_f.close()
    
    # 2) Extract sentences and word tokens
    sentences = []
    sentence  = []
    for i, line in enumerate( conll_lines ):
        if len(line) > 0 and '\t' in line:
            features = line.split('\t')
            if len(features) != 10:
                raise Exception(' In file '+in_file+', line '+str(i)+\
                                ' with unexpected format: "'+line+'" ')
            word_id = features[0]
            token   = features[1]
            sentence.append( token )
        elif len(line)==0 or re.match('^\s+$', line):
            # End of a sentence 
            if sentence:
               # (!) Use double space instead of single space in order to distinguish
               #     word-tokenizing space from the single space in the multiwords
               #     (e.g. 'Rio de Janeiro' as a single word);
               sentences.append( '  '.join(sentence) )
            sentence = []
    if sentence:
        sentences.append( '  '.join(sentence) )
    
    # 3) Construct the estnltk's Text
    kwargs4text = {
      # Use custom tokenization utils in order to preserve exactly the same 
      # tokenization as was in the input;
      "word_tokenizer": RegexpTokenizer("  ", gaps=True),
      "sentence_tokenizer": LineTokenizer()
    }
    text = Text( '\n'.join(sentences), **kwargs4text )
    # Tokenize up to the words layer
    text.tokenize_words()
    
    # 4) Align syntactic analyses with the Text
    alignments = align_CONLL_with_Text( conll_lines, text, **kwargs )
    normalise_alignments( alignments, type='CONLL', **kwargs )
    # Attach alignments to the text
    text[ layer_name ] = alignments
    return text


# ==================================================================================
# ==================================================================================
#   Building  syntactic trees from the syntactic analyses
# ==================================================================================
# ==================================================================================


class Tree(object):
    word_id     = None    # -> int    # tipule vastava sõna indeks lauses
    gen_word_id = None    # -> int    # tipule vastava sõna indeks tekstis

    labels      = None    # -> [str]  # tipu süntaksimärgendite (nt "@SUBJ", "@OBJ" jne) list; 
                          #           # mitmesuse korral võib tipul olla mitu märgendit;

    parent      = None    # -> Tree   # ülem lauses (Tree objekt)
    children    = None    # -> [Tree] # list kõigist otsestest alamatest (Tree objektid)

    token       = None    # -> dict   # Sõnale vastav EstNLTK token
    text        = None    # -> str    # Sõnale vastav TEXT ( EstNLTK  token[TEXT] )
    morph       = None    # -> [dict] # Sõnale vastav EstNLTK token[ANALYSIS] 

    parser        = None  # -> str    # Kasutatud parseri nimi: 'maltparser' või 'vislcg3'
    parser_output = None  # -> [str]  # Parseri poolt väljastatud analüüsiread (kui on säilitatud);
                          #           # mitmesuse korral võib olla mitu analüüsirida;

    def __init__( self, token, word_id, labels, parser, **kwargs ):
        self.token   = token
        self.word_id = word_id
        self.labels  = labels
        self.parser  = parser
        # TODO
        self.parent   = None
        self.children = None

    def add_child_to_self(self, tree):
        # TODO
        pass


    def add_child_to_subtree(self, word_id, tree):
        # TODO
        pass


    def get_root( self, **kwargs ):
        # TODO
        pass


    def get_children( self, **kwargs ):
        # TODO
        pass
    
    

        

# ==================================================================================
# ==================================================================================

class SyntacticParser(object):
    """ TODO: add implementation here."""
    
    def parse_text(self, text):
        """ TODO: Tag the given text instance. """
        pass
