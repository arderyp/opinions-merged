#!/usr/bin/env python

import os, flask, rfc3339, json, time, requests

from flask import Flask, jsonify, render_template, request
from sqlalchemy import func, select, desc
from flask.ext.sqlalchemy import SQLAlchemy, Pagination

# create/config our app

app = flask.Flask(__name__)
db = SQLAlchemy(app)

if 'DATABASE_URL' in os.environ:
    db_uri = os.environ['DATABASE_URL']
else:
    db_uri = 'sqlite:///' + os.path.join(app.root_path, 'opinions.db')

app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['DEBUG'] = os.environ.get("DEBUG", False)
app.config['PROPAGATE_EXCEPTIONS'] = True

def checkArchives(url):
        UA = "Opinions <http://github.com/edsu/opinions>"
        loc = "http://loc-wm.archive.org/all/*/" + url
        ia = "https://web.archive.org/web/*/" + url
        white = '#FFFFFF'
        green = '#A9F5A9'
        bg_colors = []

        for archive in loc, ia:
                resp = requests.get(archive, headers={"User-Agent": UA})
                if resp.status_code == 200:
                        bg_colors.append(green)
                else:
                        bg_colors.append(white)
        return bg_colors[0], bg_colors[1]


# database models

class Opinion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(15), nullable=False)
    created = db.Column(db.DateTime)
    published = db.Column(db.DateTime)
    name = db.Column(db.Text)
    pdf_url = db.Column(db.Text)
    reporter_id = db.Column(db.Text)
    docket_num = db.Column(db.Text)
    part_num = db.Column(db.Text)

    author_id = db.Column(db.String(5), db.ForeignKey('author.id'))
    author = db.relationship('Author',
        backref=db.backref('opinions', lazy='dynamic'))

    def published_rfc3339(self):
        return rfc3339.rfc3339(self.published)

    def __init__(self, **kwargs):
        for name, value in kwargs.items():
            if hasattr(self, name):
                setattr(self, name, value)

    def __repr__(self):
        d = self.published.strftime("%Y-%m-%d")
        return "%s (%s) <%s>" % (self.name, d, self.pdf_url)

class ExternalUrl(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.Text)
    iaBG = db.Column(db.Text)
    lcBG = db.Column(db.Text)
    edited = db.Column(db.Boolean)
    verified = db.Column(db.Boolean)
    created = db.Column(db.DateTime)
    hostname = db.Column(db.Text)
    internet_archive = db.Column(db.Text)
    opinion_id = db.Column(db.Integer, db.ForeignKey('opinion.id'))
    opinion = db.relationship('Opinion',
        backref=db.backref('external_urls', lazy='dynamic'))

    def url_cleaned(self):
        mpa = dict.fromkeys(range(32))
        return self.url.translate(mpa)

class Author(db.Model):
    id = db.Column(db.String(5), primary_key=True)
    name = db.Column(db.Text)

    def __init__(self, id=None, name=None):
        self.id = id
        self.name = name
    
    def urls(self):
        return ExternalUrl.query.join(Opinion).join(Author).order_by(Opinion.published.desc()).filter(Opinion.author_id == self.id)

    def url_ratio(self):
        return "%02.1f" % (self.urls().count() / float(self.opinions.count()))

    def wikipedia_url(self):
        # TODO: maybe put these in the db?
        w = {
            'DS': 'https://en.wikipedia.org/wiki/David_Souter',
            'T': 'https://en.wikipedia.org/wiki/Clarence_thomas',
            'JS': 'https://en.wikipedia.org/wiki/John_Paul_Stephens',
            'G': 'https://en.wikipedia.org/wiki/Ruth_Bader_Ginsburg',
            'B': 'https://en.wikipedia.org/wiki/Stephen_Breyer',
            'A': 'https://en.wikipedia.org/wiki/Samuel_alito',
            'R': 'https://en.wikipedia.org/wiki/John_g_roberts',
            'AS': 'https://en.wikipedia.org/wiki/Antonin_Scalia',
            'K': 'https://en.wikipedia.org/wiki/Anthony_Kennedy',
            'SS': 'https://en.wikipedia.org/wiki/Sonia_Sotomayor',
            'EK': 'https://en.wikipedia.org/wiki/Elana_Kagan'
        }
        if self.id in w:
            return w[self.id]
        return None


# web app

@app.route('/')
def home():
    return flask.render_template('home.html')

@app.route('/opinions/')
def opinions():
    opinions = Opinion.query.join(Author).order_by(Opinion.published.desc()).all()
    return flask.render_template('opinions.html', opinions=opinions)

@app.route('/urls/')
def urls():
    loc = "http://loc-wm.archive.org/all/*/"
    ia = "https://web.archive.org/web/*/"
    urls = ExternalUrl.query.join(Opinion).order_by(Opinion.published.desc())
    return flask.render_template('urls.html', urls=urls, ia=ia, loc=loc)

@app.route('/urls.csv')
def urls_csv():
    def generate():
        for u in ExternalUrl.query.join(Opinion).order_by(Opinion.published.desc()):
            row = [u.url, u.opinion.name, u.opinion.published, u.opinion.author.name]
            row = ['"%s"' % s for s in row]
            yield ','.join(row) + "\n"
    return flask.Response(generate(), mimetype="text/csv")


@app.route('/update/', methods=['POST'])
def update_url():

    dateTime = time.strftime("%c")
    old = request.form['old']
    new = request.form['new']
    log_message = "\nUPDATE function run on " + dateTime + """
        old = """ + old + """
        new = """ + new + "\n"
    test = open('update.log','a+')
    test.write(log_message)
    test.close

    record = db.session.query(ExternalUrl).filter_by(url=old).first()
    record.url = new
    record.lcBG, record.iaBG = checkArchives(new)
    record.edited = True
    db.session.commit()

    return jsonify(result={"status": 200})


@app.route('/author/<author_id>/')
def author(author_id):
    author = Author.query.get(author_id)
    urls = ExternalUrl.query.join(Opinion).join(Author).order_by(Opinion.published.desc()).filter(Opinion.author_id == author_id)
    return flask.render_template('author.html', urls=urls, author=author)

@app.route('/authors.csv')
def authors_csv():
    q = (select([Author.id, Author.name,
        func.count(ExternalUrl.id).label("urls")]).
         where(Author.id == Opinion.author_id).
         where(Opinion.id == ExternalUrl.opinion_id).
         group_by(Author.name, Author.id).
         order_by(desc("urls")).
         alias())
    cursor = db.session.query(q)
    results = ['id,name,urls']
    for row in cursor:
        results.append('"%s","%s",%s' % row)

    return flask.Response('\n'.join(results), mimetype='text/csv')

@app.route('/feed/')
def feed():
    opinions = Opinion.query.join(Author).outerjoin(ExternalUrl).order_by(desc(Opinion.published))
    opinions = opinions.paginate(1, 50)
    host = flask.request.headers['Host']
    feed_url = 'http://' + host + '/feed/'

    last_opinion = Opinion.query.order_by(desc(Opinion.created)).first()
    updated = rfc3339.rfc3339(last_opinion.created)

    xml = flask.render_template('feed.xml', opinions=opinions, 
        feed_url=feed_url, updated=updated)

    return flask.Response(xml, mimetype='application/atom+xml')


if __name__ == "__main__":
    db.create_all()
    app.run()
