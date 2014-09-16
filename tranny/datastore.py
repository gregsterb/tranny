# -*- coding: utf-8 -*-
from __future__ import unicode_literals, absolute_import
from collections import defaultdict
import logging
from sqlalchemy.exc import DBAPIError
from tranny import parser
from tranny import constants
from tranny.models import Section, Source, User, Download, Genre, Person

log = logging.getLogger(__name__)

cache_section = defaultdict(lambda: False)
cache_release = defaultdict(lambda: False)
cache_source = defaultdict(lambda: False)


class BaseReleaseKey(object):
    """
    Basic info for a release used to make a unique identifier for a release name
    """
    def __init__(self, release_name, name, release_key=None, media_type=constants.MEDIA_UNKNOWN):
        self.release_name = release_name
        self.name = name
        self.release_key = release_key or name
        self.media_type = media_type

    def __unicode__(self):
        return self.release_key

    def __str__(self):
        return bytes(self.release_key)

    def __eq__(self, other):
        return other == self.release_key

    def as_unicode(self):
        return "{}".format(self)


class TVReleaseKey(BaseReleaseKey):
    def __init__(self, release_name, name, season, episode, year=None):
        super(TVReleaseKey, self).__init__(
            release_name,
            name,
            "{}-{}_{}".format(name, season, episode),
            media_type=constants.MEDIA_TV
        )
        self.season = season
        self.episode = episode
        self.year = year
        self.daily = False


class TVDailyReleaseKey(BaseReleaseKey):
    def __init__(self, release_name, name, day, month, year):
        super(TVDailyReleaseKey, self).__init__(
            release_name,
            name,
            release_key="{}-{}_{}_{}".format(name, year, month, day),
            media_type=constants.MEDIA_TV
        )
        self.day = day
        self.month = month
        self.year = year
        self.daily = True


class MovieReleaseKey(BaseReleaseKey):
    def __init__(self, release_name, name, year):
        super(MovieReleaseKey, self).__init__(
            release_name,
            name,
            "{}-{}".format(name, year),
            media_type=constants.MEDIA_MOVIE
        )
        self.year = year


def generate_release_key(release_name):
    """ Generate a key suitable for using as a database key value

    :param release_name: Release name to generate a key from
    :type release_name: str, unicode
    :return: Database suitable key name
    :rtype: BaseReleaseKey
    """
    release_name = parser.normalize(release_name)
    name = parser.parse_release(release_name)
    if not name:
        return False
    name = name.lower()
    release_info = BaseReleaseKey(release_name, name)
    try:
        info = parser.parse_release_info(release_name)
    except TypeError:
        # No release info parsed use default value for key: name
        pass
    else:
        if info:
            key_set = set(info.keys())
            if key_set == {"season", "episode"}:
                release_info = TVReleaseKey(release_name, name, info['season'], info['episode'])
            elif key_set == {"year", "day", "month"}:
                release_info = TVDailyReleaseKey(release_name, name, info['day'], info['month'], info['year'])
            elif key_set == {"year"}:
                release_info = MovieReleaseKey(release_name, name, info['year'])
    finally:
        return release_info


def get_section(session, section_name=None, section_id=None):
    if section_name:
        section = session.query(Section).filter_by(section_name=section_name).first()
    elif section_id:
        section = session.query(Section).filter_by(section_id=section_id).first()
    else:
        return session.query(Section).all()
    if not section and section_name:
        section = Section(section_name)
        session.add(section)
    return section


def get_source(session, source_name=None, source_id=None):
    if source_name:
        source = cache_source[source_name]
        if not source:
            source = session.query(Source).filter_by(source_name=source_name).first()
            cache_source[source_name] = source
    elif source_id:
        for source in cache_source.values():
            if source.source_id == source_id:
                break
        else:
            source = session.query(Source).filter_by(source_id=source_id).first()
            cache_source[source.source_name] = source
    else:
        return session.query(Source).all()
    if not source and source_name:
        source = Source(source_name)
        session.add(source)
    elif not source:
        raise ValueError("Invalid source name")
    return source


def get_genre(session, genre_name, create=True):
    genre = session.query(Genre).filter(Genre.genre_name == genre_name.title()).first()
    if not genre and create:
        genre = Genre(genre_name)
        session.add(genre)
        log.info("Created new genre: {}".format(genre.genre_name))
    return genre


def get_person_imdb(session, imdb_person_id, name=None, create=True):
    person = session.query(Person).filter(Person.imdb_person_id == imdb_person_id).first()
    if not person and create:
        person = Person(imdb_person_id, name=name)
        session.add(person)
        log.info("Created new person: {}".format(name))
    return person


def fetch_download(session, release_key=None, download_id=None, limit=None):
    if release_key:
        data_set = session.query(Download).query.filter_by(release_key=release_key).first()
    elif download_id:
        data_set = session.query(Download).filter_by(download_id=download_id).first()
    else:
        data_set = session.query(Download).\
            order_by(Download.created_on.desc()).\
            limit(limit).\
            all()
    return data_set


def fetch_user(session, user_name=None, user_id=None, limit=None):
    """

    :param session:
    :type session: sqlalchemy.orm.session.Session
    :param user_name:
    :type user_name:
    :param user_id:
    :type user_id:
    :param limit:
    :type limit:
    :return:
    :rtype: User, User[]
    """
    if user_name:
        data_set = session.query(User).filter_by(user_name=user_name).first()
    elif user_id:
        data_set = session.query(User).filter_by(user_id=user_id).first()
    else:
        data_set = session.query(User).limit(limit).all()
    return data_set


def db_drop():
    from tranny.app import Base, engine
    for tbl in reversed(Base.metadata.sorted_tables):
        log.info("Dropping: {}".format(tbl.name))
        tbl.drop(engine)
    return True


def db_init(username="admin", password="tranny", wipe=False):
    from tranny.app import Base, engine, Session
    Session.configure(bind=engine)
    try:
        if wipe:
            db_drop()
        Base.metadata.create_all(bind=engine)
    except DBAPIError:
        log.exception("Failed to initialize db schema")
    else:
        log.info("Initialized db schema successfully")
        session = Session()
        try:
            admin = User(user_name=username, password=password, role=constants.ROLE_ADMIN)
            session.add(admin)
            session.commit()
        except DBAPIError:
            session.rollback()
        else:
            log.info("Created admin user successfully")
            return True
    return False
