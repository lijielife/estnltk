# -*- coding: utf-8 -*- 
#
#      Support for parsing EstNLTK texts with Java-based Maltparser
#     with the goal of obtaining syntactic dependencies between words;
#
#     Current performance:
#     1) model 'estnltkBasedDep2' (default):
#      (adds both dependency relations, and surface syntactic labels)
#      accuracy / Metric:LA   accuracy / Metric:UAS   accuracy / Metric:LAS   Token
#      --------------------------------------------------------------------------------
#      0.789                  0.801                   0.72                    Row mean
#      24208                  24208                   24208                   Row count
#      --------------------------------------------------------------------------------
#
#     2) model 'estnltkBasedDep' (former model):
#      (only adds dependency relations, no syntactic labels)
#      accuracy / Metric:UAS     Token
#      -------------------------------------
#      0.786                     Row mean
#      24208                     Row count
#      -------------------------------------
#
#    Note: The MaltParser's main class is accessible from: estntlk.syntax.parsers.Maltparser
#


from __future__ import unicode_literals, print_function
from estnltk.names import *

from estnltk.core import PACKAGE_PATH

import re, json
import os, os.path
import codecs
import tempfile
import subprocess

MALTPARSER_PATH  = os.path.join(PACKAGE_PATH, 'java-res', 'maltparser')
MALTPARSER_MODEL = 'estnltkBasedDep2'
MALTPARSER_JAR   = 'maltparser-1.9.0.jar'


# (!) Note: using these constants will be deprecated in the future versions of the parser:
SYNTAX_LABEL = 's_label' # from dependency link: index of the current token in the syntactic tree
SYNTAX_HEAD  = 's_head'  # from dependency link: index of current token's parent in the syntactic tree
DEPREL       = 's_rel'   # from dependency link: surface-syntactic label of the relation


# =============================================================================
# =============================================================================
#  Generating features to be used in CONLL
# =============================================================================
# =============================================================================

class CONLLFeatGenerator(object):
    ''' Class for generating CONLL format "features" from EstNLTK's sentences.
    
         More specifically, the generated "features" include fields ID, FORM, 
        LEMMA, CPOSTAG, POSTAG, FEATS of a CONLL format line.
         At each feature-generation step, the generator gets a word and a 
        sentence the word belongs to as an input, and generates features of the 
        given word as an output;
    ''' 
    
    addAmbiguousPos = False
    kSubCatRelsLex  = None
    kFeatures       = None
    
    def __init__( self, **kwargs):
       ''' Initializes CONLLFeatGenerator with the configuration given in 
           the keyword arguments;
           
           Parameters
           -----------
           addAmbiguousPos : bool
                If True, the words having an ambiguous part-of-speech will have
                their POSTAG field (fine-grained POS tag) filled with a 
                contatenation of all ambiguous POS tags; If False, POSTAG field
                is the same as CPOSTAG;
                Default: True
           addKSubCatRels : string 
                If used, the argument value should contain a location of the 
                _K_ subcategorization relations file -- a file that can be loaded 
                via method _loadKSubcatRelations();
                Then the dictionary loaded from file is used to provide more 
                fine-grained information about postposition/preposition tokens 
                (K tokens); 
                Default: None
       '''
       # ** Parse keyword arguments
       for argName, argVal in kwargs.items():
            if argName in ['addAmbiguousPos']:
                self.addAmbiguousPos = bool(argVal)
            elif argName in ['addKSubCatRels', 'kSubCatRels']:
                if os.path.isfile(argVal):
                    # Load K subcategorization lexicon from file
                    self.kSubCatRelsLex = _loadKSubcatRelations( argVal )
                else:
                    raise Exception('(!) Lexicon file not found: ',argVal)


    def generate_features( self, sentence_text, wid ):
        ''' Generates and returns a list of strings, containing tab-separated 
            features ID, FORM, LEMMA, CPOSTAG, POSTAG, FEATS of the word
            (the word with index *wid* from the given *sentence_text*).
            
            Parameters
            -----------
            sentence_text : estnltk.text.Text
                Text object corresponding to a single sentence. 
                Words of the sentence, along with their morphological analyses, 
                should be accessible via the layer WORDS.
                And each word should be a dict, containing morphological features 
                in ANALYSIS part;
            
            wid : int
                Index of the word/token, whose features need to be generated;

        '''
        assert WORDS in sentence_text and len(sentence_text[WORDS])>0, \
               " (!) 'words' layer missing or empty in given Text!"
        sentence = sentence_text[WORDS]
        assert -1 < wid and wid < len(sentence), ' (!) Invalid word id: '+str(wid)
        
        # 1) Pre-process (if required)
        if wid == 0 and self.kSubCatRelsLex:
            self.kFeatures = \
                _findKsubcatFeatures( sentence, self.kSubCatRelsLex, addFeaturesToK = True )

        # 2) Generate the features
        estnltkWord = sentence[wid]
        # Pick the first analysis
        firstAnalysis = estnltkWord[ANALYSIS][0]
        strForm = []
        # *** ID
        strForm.append( str(wid+1) )
        strForm.append( '\t' )
        # *** FORM
        word_text = estnltkWord[TEXT]
        word_text = word_text.replace(' ', '_')
        strForm.append( word_text )
        strForm.append( '\t' )
        # *** LEMMA
        word_root = firstAnalysis[ROOT]
        word_root = word_root.replace(' ', '_')
        if len(word_root) == 0:
            word_root = "??"
        strForm.append( word_root )
        strForm.append( '\t' )
        # *** CPOSTAG
        strForm.append( firstAnalysis[POSTAG] )
        strForm.append( '\t' )
        # *** POSTAG
        finePos = firstAnalysis[POSTAG]
        if self.addAmbiguousPos and len(estnltkWord[ANALYSIS]) > 1:
            pos_tags = sorted(list(set([ a[POSTAG] for a in estnltkWord[ANALYSIS] ])))
            finePos  = '_'.join(pos_tags)
        if self.kFeatures and i in self.kFeatures:
            finePos += '|'+self.kFeatures[i]
        strForm.append( finePos )
        strForm.append( '\t' )
        # *** FEATS  (grammatical categories)
        grammCats = '_'
        if len(firstAnalysis[FORM]) != 0:
            forms = firstAnalysis[FORM].split()
            grammCats = '|'.join(forms)
        strForm.append( grammCats )
        strForm.append( '\t' )
        return strForm


# =============================================================================
# =============================================================================
#  Converting data from estnltk JSON to CONLL
# =============================================================================
# =============================================================================

def __sort_analyses(sentence):
    ''' Sorts analysis of all the words in the sentence. 
        This is required for consistency, because by default, analyses are 
        listed in arbitrary order; '''
    for word in sentence:
        if ANALYSIS not in word:
            raise Exception( '(!) Error: no analysis found from word: '+str(word) )
        else:
            word[ANALYSIS] = sorted(word[ANALYSIS], \
                key=lambda x : "_".join( [x[ROOT],x[POSTAG],x[FORM],x[CLITIC]] ))
    return sentence


def convert_text_to_CONLL( text, feature_generator ):
    ''' Converts given estnltk Text object into CONLL format and returns as a 
        string.
        Uses given *feature_generator* to produce fields ID, FORM, LEMMA, CPOSTAG, 
        POSTAG, FEATS for each token.
        Fields to predict (HEAD, DEPREL) will be left empty.
        This method is used in preparing parsing & testing data for MaltParser.
        
        Parameters
        -----------
        text : estnltk.text.Text
            Morphologically analysed text from which the CONLL file is generated;
            
        feature_generator : CONLLFeatGenerator
            An instance of CONLLFeatGenerator, which has method *generate_features()* 
            for generating morphological features for a single token;
            
        
        The aimed format looks something like this:
        1	Öö	öö	S	S	sg|nom	_	xxx	_	_
        2	oli	ole	V	V	indic|impf|ps3|sg	_	xxx	_	_
        3	täiesti	täiesti	D	D	_	_	xxx	_	_
        4	tuuletu	tuuletu	A	A	sg|nom	_	xxx	_	_
        5	.	.	Z	Z	Fst	_	xxx	_	_

    '''
    from estnltk.text import Text
    if not isinstance( text, Text ):
        raise Exception('(!) Unexpected type of input argument! Expected EstNLTK\'s Text. ')
    sentenceStrs = []
    for sentence_text in text.split_by( SENTENCES ):
        sentence_text[WORDS] = __sort_analyses( sentence_text[WORDS] )
        for i in range(len( sentence_text[WORDS] )):
            # Generate features  ID, FORM, LEMMA, CPOSTAG, POSTAG, FEATS
            strForm = feature_generator.generate_features( sentence_text, i )
            # *** HEAD  (syntactic parent)
            strForm.append( '_' )
            strForm.append( '\t' )
            # *** DEPREL  (label of the syntactic relation)
            strForm.append( 'xxx' )
            strForm.append( '\t' )
            # *** PHEAD
            strForm.append( '_' )
            strForm.append( '\t' )
            # *** PDEPREL
            strForm.append( '_' )
            sentenceStrs.append( ''.join( strForm ) )
        sentenceStrs.append( '' )
    return '\n'.join( sentenceStrs )


def convert_text_w_syntax_to_CONLL( text, feature_generator, layer=LAYER_CONLL ):
    ''' Converts given estnltk Text object into CONLL format and returns as a 
        string.
        Uses given *feature_generator* to produce fields ID, FORM, LEMMA, CPOSTAG, 
        POSTAG, FEATS for each token.
        Fills fields to predict (HEAD, DEPREL) with the syntactic information from
        given *layer* (default: LAYER_CONLL).
        This method is used in preparing training data for MaltParser.
        
        Parameters
        -----------
        text : estnltk.text.Text
            Morphologically analysed text from which the CONLL file is generated;
            
        feature_generator : CONLLFeatGenerator
            An instance of CONLLFeatGenerator, which has method *generate_features()* 
            for generating morphological features for a single token;
        
        layer : str
            Name of the *text* layer from which syntactic information is to be taken.
            Defaults to LAYER_CONLL.
        
        The aimed format looks something like this:
        1	Öö	öö	S	S	sg|n	2	@SUBJ	_	_
        2	oli	ole	V	V	s	0	ROOT	_	_
        3	täiesti	täiesti	D	D	_	4	@ADVL	_	_
        4	tuuletu	tuuletu	A	A	sg|n	2	@PRD	_	_
        5	.	.	Z	Z	_	4	xxx	_	_

    '''
    from estnltk.text import Text
    if not isinstance( text, Text ):
        raise Exception('(!) Unexpected type of input argument! Expected EstNLTK\'s Text. ')
    assert layer in text, ' (!) The layer "'+layer+'" is missing form the Text object.'
    sentenceStrs = []
    for sentence_text in text.split_by( SENTENCES ):
        sentence_text[WORDS] = __sort_analyses( sentence_text[WORDS] )
        for i in range(len( sentence_text[WORDS] )):
            # Generate features  ID, FORM, LEMMA, CPOSTAG, POSTAG, FEATS
            strForm = feature_generator.generate_features( sentence_text, i )
            # Get syntactic analysis of the token
            syntaxToken    = sentence_text[layer][i]
            firstSyntaxRel = syntaxToken[PARSER_OUT][0]
            # *** HEAD  (syntactic parent)
            parentLabel = str( firstSyntaxRel[1] + 1 )
            strForm.append( parentLabel )
            strForm.append( '\t' )
            # *** DEPREL  (label of the syntactic relation)
            if parentLabel == '0':
                strForm.append( 'ROOT' )
                strForm.append( '\t' )
            else:
                strForm.append( firstSyntaxRel[0] )
                strForm.append( '\t' )
            # *** PHEAD
            strForm.append( '_' )
            strForm.append( '\t' )
            # *** PDEPREL
            strForm.append( '_' )
            sentenceStrs.append( ''.join( strForm ) )
        sentenceStrs.append( '' )
    return '\n'.join( sentenceStrs )


# =============================================================================
# =============================================================================
#  Executing MaltParser on CONLL formatted estnltk Text
# =============================================================================
# =============================================================================

def _executeMaltparser( input_string, maltparser_dir, maltparser_jar, model_name ):
    ''' Executes Maltparser on given (CONLL-style) input string, and 
        returns the result. The result is an array of lines from Maltparser's 
        output.
        
        Parameters
        ----------
        input_string: string
              input text in CONLL format;
        maltparser_jar: string
              name of the Maltparser's jar file that should be executed;
        model_name: string
              name of the model that should be used;
        maltparser_dir: string
              the directory containing Maltparser's jar and the model file; 
        
        Few of the ideas were also borrowed from NLTK's MaltParser class,
        see  http://www.nltk.org/_modules/nltk/parse/malt.html   for the reference;
    '''

    temp_input_file = \
      tempfile.NamedTemporaryFile(prefix='malt_in.', mode='w', delete=False)
    temp_input_file.close()
    # We have to open separately here for writing, because Py 2.7 does not support
    # passing parameter   encoding='utf-8'    to the NamedTemporaryFile;
    out_f = codecs.open(temp_input_file.name, mode='w', encoding='utf-8')
    out_f.write( input_string )
    out_f.close()

    temp_output_file = tempfile.NamedTemporaryFile(prefix='malt_out.', mode='w', delete=False)
    temp_output_file.close()
    
    current_dir = os.getcwd()
    os.chdir(maltparser_dir)
    cmd = ['java', '-jar', os.path.join(maltparser_dir, maltparser_jar), \
           '-c', model_name, \
           '-i', temp_input_file.name, \
           '-o', temp_output_file.name, \
           '-m', 'parse' ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.wait() != 0: 
        raise Exception(' Error on running Maltparser: ', p.stderr.read() )
    os.chdir(current_dir)
    
    results = []
    in_f = codecs.open(temp_output_file.name, mode='r', encoding='utf-8')
    for line in in_f:
        results.append( line.rstrip() )
    in_f.close()

    if not temp_input_file.closed:
        raise Exception('Temp input file unclosed!')
    if not temp_output_file.closed:
        raise Exception('Temp input file unclosed!')
    if not out_f.closed:
        raise Exception('Output file unclosed!')
    if not in_f.closed:
        raise Exception('Input file unclosed!')
    # TODO: For some reason, the method gives "ResourceWarning: unclosed file"
    # in Python 3.4, although, apparently, all file handles seem to be closed;
    # Nothing seems to be wrong in Python 2.7;

    os.remove(temp_input_file.name)
    os.remove(temp_output_file.name)

    return results

# =============================================================================
# =============================================================================
#  Converting data from CONLL to estnltk JSON
# =============================================================================
# =============================================================================

def loadCONLLannotations( in_file, addDepRels = False, splitIntoSentences = True ):
    ''' Loads syntactically annotated text from CONLL format input file and 
        returns as an array of tokens, where each token is represented as 
        an array in the format:
           [sentenceID, wordID, tokenString, morphInfo, selfID, parentID]
        If addDepRels == True, then the dependency relation label is also extracted
        and added to the end of the array:
           [sentenceID, wordID, tokenString, morphInfo, selfID, parentID, depRel]
        If splitIntoSentences == True, the array of tokens is further divided
        into subarrays representing sentences.
        
         Example input:
        2	Monstrumteleskoobid	Monstrum_tele_skoop	S	S	prop|pl|nom	0	ROOT	_	_
        3	(	(	Z	Z	Opr	4	xxx	_	_
        4	mosaiik-	mosaiik	A	A	pos|sg|nom	2	@<AN	_	_
        5	ja	ja	J	J	crd	6	@J	_	_
        6	mitmepeeglilised	mitme_peegli=line	A	A	pos|pl|nom	4	@<NN	_	_
        7	)	)	Z	Z	Cpr	6	xxx	_	_
        8	.	.	Z	Z	Fst	7	xxx	_	_
        
    '''
    sentenceCount   = 0
    wordCountInSent = 0
    tokens = []
    in_f = codecs.open(in_file, mode='r', encoding='utf-8')
    for line in in_f:
        line = line.rstrip()
        if len(line) == 0 or re.match('^\s+$', line):
            sentenceCount += 1
            wordCountInSent = 0
            continue
        features = line.split('\t')
        if len(features) != 10:
            raise Exception(' In file '+in_file+', line with unexpected format: "'+line+'" ')
        selfLabel   = features[0]
        token       = features[1]
        lemma       = features[2]
        cpos        = features[3]
        pos         = features[4]
        form        = features[5]
        parentLabel = features[6]
        tokens.append( [ str(sentenceCount), str(wordCountInSent), \
                         token, lemma+" "+pos+" "+form, selfLabel, parentLabel ] )
        if addDepRels:
            tokens[-1].append( features[7] )
        wordCountInSent += 1
    in_f.close()
    if not splitIntoSentences:
        return tokens
    else:
        sentences = []
        lastSentID = ''
        for tok in tokens:
            if tok[0] != lastSentID:
                sentences.append([])
            sentences[-1].append(tok)
            lastSentID = tok[0]
        return sentences


def convertCONLLtoText( in_file, addDepRels = False, verbose = False, **kwargs ):
    ''' Loads CONLL format data from given input file, and creates
        estnltk Text objects from the data, one Text per each 
        sentence. Returns a list of Text objects.
        
        By default, applies estnltk's morphological analysis, clause 
        detection, and verb chain detection to each input sentence.
        
        If addDepRels == True, in addition to SYNTAX_LABEL and SYNTAX_HEAD,
        surface syntactic function (DEPREL) is also attributed to each 
        token;
    '''
    from estnltk.text import Text
    sentences = loadCONLLannotations( in_file, addDepRels = addDepRels, \
                                               splitIntoSentences = True )
    if verbose:
        print( str(len(sentences))+' sentences loaded. ')
    estnltkSentTexts = []
    for i in range(len(sentences)):
        s  = sentences[i]
        sentenceString = " ".join( [ t[2] for t in s ] )
        sentText = Text(sentenceString, **kwargs)
        sentText.tag_analysis()
        sentText.tag_clauses()
        sentText.tag_verb_chains()
        sentText = dict(sentText)
        if len(sentText[WORDS]) == len(s):
            # Add the dependency syntactic information
            for j in range(len(sentText[WORDS])):
                estnltkWord   = sentText[WORDS][j]
                depSyntaxWord = s[j]
                estnltkWord[SYNTAX_LABEL] = depSyntaxWord[4]
                estnltkWord[SYNTAX_HEAD]  = depSyntaxWord[5]
                if addDepRels:
                   estnltkWord[DEPREL] = depSyntaxWord[6]
            estnltkSentTexts.append( sentText )
            if verbose:
                print ('*', end = '')
        else:
            if verbose:
                print("The sentence segmentation of dependency syntax differs from the estnltk's sentence segmentation:", len(sentText[WORDS]), ' vs ',len(s))
    return estnltkSentTexts


def augmentTextWithCONLLstr( conll_str_array, text ):
    ''' Augments given Text object with the information from Maltparser's output.
        More specifically, adds information about SYNTAX_LABEL, SYNTAX_HEAD and
        DEPREL to each token in the Text object;
    '''
    j = 0
    for sentence in text.divide( layer=WORDS, by=SENTENCES ):
        sentence = __sort_analyses(sentence)
        for i in range(len(sentence)):
            estnltkToken    = sentence[i]
            maltparserToken = conll_str_array[j]
            if len( maltparserToken ) > 1:
                maltParserAnalysis = maltparserToken.split('\t')
                if estnltkToken[TEXT] == maltParserAnalysis[1]:
                    # Fetch information about the syntactic relation:
                    estnltkToken[SYNTAX_LABEL] = maltParserAnalysis[0]
                    estnltkToken[SYNTAX_HEAD]  = maltParserAnalysis[6]
                    # Fetch the name of the surface syntactic relation
                    estnltkToken[DEPREL]       = maltParserAnalysis[7]
                else:
                    raise Exception("A misalignment between Text and Maltparser's output: ",\
                        estnltkToken, maltparserToken )
            j += 1
        j += 1


def align_CONLL_with_Text( lines, text, **kwargs ):
    ''' Aligns CONLL format syntactic analysis (a list of strings) with given EstNLTK's Text 
        object.
        Basically, for each word position in the Text object, finds corresponding line(s) in
        the CONLL format output;

        Returns a list of dicts, where each dict has following attributes:
          'start'   -- start index of the word in Text;
          'end'     -- end index of the word in Text;
          'sent_id' -- index of the sentence in Text, starting from 0;
          'parser_out' -- list of analyses from the output of the syntactic parser;

        Parameters
        -----------
        lines : list of str
            The input text for the pipeline; Should be the CONLL format syntactic analysis;

        text : Text
            EstNLTK Text object containing the original text that was analysed with
            MaltParser;

        check_tokens : bool
            Optional argument specifying whether tokens should be checked for match 
            during the alignment. In case of a mismatch, an exception is raised.
            Default:False
            
        add_word_ids : bool
            Optional argument specifying whether each alignment should include attributes:
            * 'text_word_id' - current word index in the whole Text, starting from 0;
            * 'sent_word_id' - index of the current word in the sentence, starting from 0;
            Default:False
        
    ''' 
    from estnltk.text import Text
    if not isinstance( text, Text ):
        raise Exception('(!) Unexpected type of input argument! Expected EstNLTK\'s Text. ')
    if not isinstance( lines, list ):
        raise Exception('(!) Unexpected type of input argument! Expected a list of strings.')
    check_tokens = False
    add_word_ids = False
    for argName, argVal in kwargs.items() :
        if argName in ['check_tokens', 'check'] and argVal in [True, False]:
           check_tokens = argVal
        if argName in ['add_word_ids', 'word_ids'] and argVal in [True, False]:
           add_word_ids = argVal
    generalWID = 0
    sentenceID = 0
    # Iterate over the sentences and perform the alignment
    results = []
    j = 0
    for sentence in text.divide( layer=WORDS, by=SENTENCES ):
        for i in range(len(sentence)):
            estnltkToken    = sentence[i]
            maltparserToken = lines[j]
            if len( maltparserToken ) > 1:
                maltParserAnalysis = maltparserToken.split('\t')
                if check_tokens and estnltkToken[TEXT] != maltParserAnalysis[1]:
                    raise Exception("(!) A misalignment between Text and CONLL: ",\
                                    estnltkToken, maltparserToken )
                # Populate the alignment
                result_dict = { START:estnltkToken[START], END:estnltkToken[END], \
                                SENT_ID:sentenceID, PARSER_OUT: [maltparserToken] }
                if add_word_ids:
                    result_dict['text_word_id'] = generalWID # word id in the text
                    result_dict['sent_word_id'] = i          # word id in the sentence
                results.append( result_dict )
            j += 1
            generalWID += 1
        sentenceID += 1
        j += 1
    return results

# =============================================================================
# =============================================================================
#   Experimental stuff:  Tuning maltparser with additional features
# =============================================================================
# =============================================================================

# =============================
#   K subcat relations
# =============================

def _loadKSubcatRelations( inputFile ):
    ''' Laeb sisendfailist (inputFile) kaassõnade rektsiooniseoste mustrid.
        Iga muster peab olema failis eraldi real, kujul:
        (sõnalemma);(sõnaliik);(post|pre);(nõutud_käänete_regexp)
        nt
            ees;_K_;post;g
            eest;_K_;post;g
            enne;_K_;pre;p
        Tagastab laetud andmed sõnastikuna;
    '''
    kSubCatRelations = dict()
    in_f = codecs.open(inputFile, mode='r', encoding='utf-8')
    for line in in_f:
        line = line.rstrip()
        if len(line) > 0 and not re.match("^#.+$", line):
            items = line.split(';')
            if len(items) == 4:
                root         = items[0]
                partofspeech = items[1]
                postPre      = items[2]
                morphPattern = items[3]
                fpattern = '(sg|pl)\s'+morphPattern
                if root not in kSubCatRelations:
                    kSubCatRelations[root] = []
                kSubCatRelations[root].append( [postPre, fpattern] )
                root_clean = root.replace('_', '')
                if root != root_clean:
                    if root_clean not in kSubCatRelations:
                        kSubCatRelations[root_clean] = []
                    kSubCatRelations[root_clean].append( [postPre, fpattern] )
            else:
                raise Exception(' Unexpected number of items in the input lexicon line: '+line)
    in_f.close()
    return kSubCatRelations


def _detectKsubcatRelType( sentence, i, kSubCatRelsLexicon ):
    ''' Given the adposition appearing in the sentence at the location i,
        checks whether the adposition appears in the kSubCatRelsLexicon, 
        and if so, attempts to further detect whether the adposition is a 
        preposition or a postposition;
         Returns a tuple (string, int), where the first item indicates the
        type of adposition ('pre', 'post', '_'), and the second item points
        to its possible child (index of the word in sentence, or -1, if 
        possible child was not detected from close range);
    ''' 
    curToken = sentence[i]
    root = curToken[ANALYSIS][0][ROOT]
    if root in kSubCatRelsLexicon:
        for [postPre, fpattern] in kSubCatRelsLexicon[root]:
            if postPre == 'post' and i-1 > -1:
                lastTokenAnalysis = sentence[i-1][ANALYSIS][0]
                if re.match(fpattern, lastTokenAnalysis[FORM]):
                    return ('post', i-1)
            elif postPre == 'pre' and i+1 < len(sentence):
                nextTokenAnalysis = sentence[i+1][ANALYSIS][0]
                if re.match(fpattern, nextTokenAnalysis[FORM]):
                    return ('pre', i+1)
        # If the word is not ambiguous between pre and post, but
        # the possible child was not detected, return only the
        # post/pre label:
        if len(kSubCatRelsLexicon[root]) == 1:
            return (kSubCatRelsLexicon[root][0][0], -1)
    return ('_', -1)


def _detectPossibleKsubcatRelsFromSent( sentence, kSubCatRelsLexicon, reverseMapping = False ):
    ''' Attempts to detect all possible K subcategorization relations from
        given sentence, using the heuristic method _detectKsubcatRelType();
        
        Returns a dictionary of relations where the key corresponds to the
        index of its parent node (the K node) and the value corresponds to 
        index of its child.
        
        If reverseMapping = True, the mapping is reversed: keys correspond
        to children and values correspond to parent nodes (K-s);
    '''
    relationIndex = dict()
    relationType  = dict()
    for i in range(len(sentence)):
        estnltkWord = sentence[i]
        # Pick the first analysis
        firstAnalysis = estnltkWord[ANALYSIS][0]
        if firstAnalysis[POSTAG] == 'K':
            (grammCats, kChild) = _detectKsubcatRelType( sentence, i, kSubCatRelsLexicon )
            if kChild != -1:
                if reverseMapping:
                    relationIndex[ kChild ] = i
                    relationType[ kChild ]  = grammCats
                else:
                    relationIndex[ i ] = kChild
                    relationType[ i ]  = grammCats
    return relationIndex, relationType


def _findKsubcatFeatures( sentence, kSubCatRelsLexicon, addFeaturesToK = True ):
    ''' Attempts to detect all possible K subcategorization relations from
        given sentence, using the heuristic methods _detectKsubcatRelType() 
        and _detectPossibleKsubcatRelsFromSent();
        
        Returns a dictionary where the keys correspond to token indices,
        and values are grammatical features related to K subcat relations.
        Not all tokens in the sentence are indexed, but only tokens relevant
        to K subcat relations;
        
        If addFeaturesToK == True, grammatical features are added to K-s,
        otherwise, grammatical features are added to K's child tokens.
    '''
    features = dict()
    # Add features to the K (adposition)
    if addFeaturesToK:
        for i in range(len(sentence)):
            estnltkWord = sentence[i]
            # Pick the first analysis
            firstAnalysis = estnltkWord[ANALYSIS][0]
            if firstAnalysis[POSTAG] == 'K':
                (grammCats, kChild) = _detectKsubcatRelType( sentence, i, kSubCatRelsLexicon )
                features[i] = grammCats
    # Add features to the noun governed by K
    else:
        relationIndex, relationType = \
            _detectPossibleKsubcatRelsFromSent( sentence, kSubCatRelsLexicon, reverseMapping = True )
        for i in relationIndex:
            features[i] = relationType[i]
    return features    

