import os
from flask import Flask, request,jsonify, make_response, current_app
import nltk
from readability.readability import Document
import wikipedia
from datetime import timedelta
from functools import update_wrapper


from datetime import timedelta
from flask import make_response, request, current_app
from functools import update_wrapper


def crossdomain(origin=None, methods=None, headers=None,
                max_age=21600, attach_to_all=True,
                automatic_options=True):
    if methods is not None:
        methods = ', '.join(sorted(x.upper() for x in methods))
    if headers is not None and not isinstance(headers, basestring):
        headers = ', '.join(x.upper() for x in headers)
    if not isinstance(origin, basestring):
        origin = ', '.join(origin)
    if isinstance(max_age, timedelta):
        max_age = max_age.total_seconds()

    def get_methods():
        if methods is not None:
            return methods

        options_resp = current_app.make_default_options_response()
        return options_resp.headers['allow']

    def decorator(f):
        def wrapped_function(*args, **kwargs):
            if automatic_options and request.method == 'OPTIONS':
                resp = current_app.make_default_options_response()
            else:
                resp = make_response(f(*args, **kwargs))
            if not attach_to_all and request.method != 'OPTIONS':
                return resp

            h = resp.headers
            h['Access-Control-Allow-Origin'] = origin
            h['Access-Control-Allow-Methods'] = get_methods()
            h['Access-Control-Max-Age'] = str(max_age)
            h['Access-Control-Allow-Credentials'] = 'true'
            h['Access-Control-Allow-Headers'] = \
                "Origin, X-Requested-With, Content-Type, Accept, Authorization"
            if headers is not None:
                h['Access-Control-Allow-Headers'] = headers
            return resp

        f.provide_automatic_options = False
        return update_wrapper(wrapped_function, f)
    return decorator

MIN_LEN = 0

app = Flask(__name__)

class RainError(Exception):
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv['message'] = self.message
        return rv

@app.errorhandler(RainError)
def handle_error(error):
	response = jsonify(error.to_dict())
	response.status_code = error.status_code
	return response

class Filters:

	def __init__(self):
		self._ne = []
		self.functions = [self.named_entities]
		return

	def named_entities(self, content, domain):
		sentences = nltk.sent_tokenize(content['raw'])
		sentences = [nltk.word_tokenize(sent) for sent in sentences]
		sentences = [nltk.pos_tag(sent) for sent in sentences]
		trees = nltk.batch_ne_chunk(sentences)
		for tree in trees:
			self._traverse(tree)
		print self._ne
		return self._ne, []


	def _traverse(self,t):
		ne = [
			'ORGANIZATION',
			'PERSON',
			'LOCATION',
			'DATE',
			'TIME',
			'MONEY',
			'PERCENT',
			'FACILITY',
			'GPE'
		]
		try:
			t.node
		except AttributeError:
			return
		else:
			if t.node in ne:
				if t not in self._ne:
					self._ne.append(t)
			else:
				for child in t:
					self._traverse(child)

	def tokenize_words(self, content, domain):
		content['tokens'] = nltk.word_tokenize(content['raw'].encode('utf-8'))
		return content, []

	def _wikipedia_card(self,query):
		try:
			page = wikipedia.page(query)
		except:
			return False
		card = {}
		card['title'] = page.title
		card['url'] = page.url
		card['summary'] = page.summary
		card['images'] = [image for image in page.images if self._filter_image(image)]
		card['images'] = card['images'][:4]
		return card

	def _filter_image(self,image):
		return ("commons" in image) and image.endswith('.jpg')

	def collocations(self,content, domain):
		text = nltk.Text(content['tokens'])
		collocations = self._collocations_from_text(text)
		cards = []
		#collocations = ['White House','health care', 'West Wing', 'Mr. Obama', 'said, ','Mr. Obama\'s', 'said one', 'Wing staff', 'Democratic lawmakers', 'staff members','President Obama', 'White House.', 'care problems', 'Mr. McDonough', 'senior']
		for phrase in collocations:
			card = self._wikipedia_card(phrase)

			cards.append(card)
		return content, cards

	def _collocations_from_text(self,text):
		window_size = 2
		num = 20
		from nltk.corpus import stopwords
		from nltk.metrics import f_measure, BigramAssocMeasures, TrigramAssocMeasures
		from nltk.collocations import BigramCollocationFinder, TrigramCollectionFinder
		ignored_words = stopwords.words('english')
		finder = BigramCollocationFinder.from_words(text.tokens, window_size)
		finder.apply_freq_filter(2)
		finder.apply_word_filter(lambda w: len(w) < 3 or w.lower() in ignored_words)
		bigram_measures = BigramAssocMeasures()
		trigram_measures = TrigramAssocMeasures()
		collocations = finder.nbest(bigram_measures.likelihood_ratio,num)
		colloc_strings = [w1+' '+w2 for w1, w2 in collocations]
		return colloc_strings

	def _similar_terms(self, term1, term2):
		import difflib
		return difflib.SequenceMatcher(a=term1.lower(), b=term2.lower()).ratio() > 0.5

def rainman(full_html, domain):
	content = parse(full_html, domain)
	cards = []
	content, cards = run_filters(content, domain)
	return jsonify(content=content, cards=cards)

def parse(full_html, domain):
	readable_html = readable(full_html, domain)
	raw = nltk.clean_html(readable_html)
	content = {}
	content['raw'] = raw
	content['readable'] = readable_html
	checkArticle(content, domain)
	return content

def run_filters(content, domain):
	cards = []
	filters = Filters()
	for f in filters.functions:
		fcontent, fcards = f(content, domain)
		content = fcontent
		cards.extend(fcards)

	return content, cards

def readable(full_html, domain):
	positive, negative = article_patterns(domain)
	readable_html = Document(full_html, positive_keywords=positive, negative_keywords=negative).summary()
	return readable_html

def article_patterns(domain):
	return [],[]

def checkArticle(content, domain):
	whitelist = []
	blacklist = []
	if (content['raw'].__len__() < MIN_LEN or domain in blacklist) and (domain not in whitelist):
		raise RainError('Not an article')

@app.route('/')
def home():
	return 'Hello World!'

@app.route('/api', methods=['POST','OPTIONS'])
@crossdomain(origin='*',headers='Content-Type')
def api():
	content = request.form['content']
	domain = request.form['domain']
	return jsonify(message='Hello')

if __name__ == '__main__':
	app.run(debug=True)