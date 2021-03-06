#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime, time

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session
from models import SessionForm
from models import SessionForms
from models import Speaker
from models import SpeakerForm
from models import SpeakerForms
from models import SpeakerQueryForm
from models import SpeakerQueryForms
from models import SessionType
from models import SessionHighlightsForm
from models import SessionSpeakerFieldForm

from utils import getUserId

from settings import WEB_CLIENT_ID

from google.appengine.api import memcache

from models import StringMessage

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
MEMCACHE_FEATUREDSPEAKER_KEY = "FEATUREDSPEAKER"

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SPEAKERDEFAULTS = {
    "company": "NOT_SPECIFIED",
    "sex": "Male",
    "field": ["NOT_SPECIFIED"],
}

SESSION_CREATE_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)

CON_SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CON_SES_TYPE_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    typeOfSession=messages.EnumField(SessionType, 2),
)

SES_SEPAKER_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
)

SESSION_DEFAULTS = {
    "highlights": ["NOT_SPECIFIED"],
}

SES_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    sessionKey=messages.StringField(1),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', 
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        # TODO 2: add confirmation email sending task to queue
        taskqueue.add(params={'email': user.email(), 'conferenceInfo': repr(request)},
                    url = '/tasks/send_confirmation_email')

        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id =  getUserId(user)
        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
            prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -
    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        # TODO 1
        # return an existing announcement from Memcache or an empty string.
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY)
        if not announcement:
            announcement = ""
        return StringMessage(data=announcement)

# - - - TASK1: Speaker - - - - - - - - - - - - - - - - - - - -
    def _createSpeakerObject(self, request):
        '''Create Speaker object, returning SpeakerForm'''
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        if not request.name:
            raise endpoints.BadRequestException("Speaker 'name' field required.")

        if not request.email:
            raise endpoints.BadRequestException("Speaker 'email' field required.")

        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        for df in SPEAKERDEFAULTS:
            if data[df] in (None, []):
                data[df] = SPEAKERDEFAULTS[df]
                setattr(request, df, SPEAKERDEFAULTS[df])

        s_key = ndb.Key(Speaker, data['email'])
        data['key'] = s_key

        Speaker(**data).put()

        return request

    def _copySpeakerToForm(self, speaker):
        '''Copy relevant fields from Speaker to SpeakerForm'''
        speaker_form = SpeakerForm()
        for field in speaker_form.all_fields():
            if hasattr(speaker, field.name):
                setattr(speaker_form, field.name, getattr(speaker, field.name))
        speaker_form.check_initialized()
        return speaker_form


    @endpoints.method(SpeakerForm, SpeakerForm, path='speaker',
            http_method='POST', name='createSpeaker')
    def createSpeaker(self, request):
        '''Create new speaker and upadte speaker.'''
        return self._createSpeakerObject(request)

    def _queryForSpeakers(self, filters):
        """
        Using the filter to query for speakers.
        Returns:
          Query results for the filters.
        Args:
          filters: the SpeakerQueryForms's filters.
        """
        formatted_filters = []
        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}
            formatted_filters.append(filtr)
        q = Speaker.query()
        q = q.order(Speaker.name)
        for filtr in formatted_filters:
            query = ndb.query.FilterNode(filtr['field'], "=", filtr['value'])
            q = q.filter(query)
        return q

    @endpoints.method(SpeakerQueryForms, SpeakerForms,
            path='querySpeakers', http_method='POST',
            name='querySpeakers')
    def querySpeakers(self, request):
        '''Query for speakers'''
        speakers = self._queryForSpeakers(request.filters)

        return SpeakerForms(items=[self._copySpeakerToForm(speaker) for speaker in speakers])

# - - - TASK1:Session - - - - - - - - - - - - - - - - - - - -
    def _createSessionObject(self, request):
        """
        Using the request to create session
        Returns:
          SessionForm: including all the session info.
        Args:
          SESSION_CREATE_REQUEST request container
        """
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        c_key = ndb.Key(urlsafe=request.websafeConferenceKey) 
        conf = c_key.get()

        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can create the session.')

        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        if not request.speaker:
            raise endpoints.BadRequestException("Session 'speaker' field required")

        speaker_key = ndb.Key(Speaker, request.speaker)
        if not speaker_key.get():
            raise endpoints.NotFoundException(
                'No speaker found with id: %s' % request.speaker)

        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeConferenceKey']
        del data['websafeKey']

        for df in SESSION_DEFAULTS:
            if data[df] in (None, []):
                data[df] = SESSION_DEFAULTS[df]
                setattr(request, df, SESSION_DEFAULTS[df])

        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()
        else:
            data['date'] = conf.startDate

        if data['startTime']:
            data['startTime'] = datetime.strptime(data['startTime'][:5], "%H:%M").time()

        if data['typeOfSession']:
            data['typeOfSession'] = str(getattr(request, 'typeOfSession'))
        else:
            data['typeOfSession'] = str(SessionType.NOT_SPECIFIED)

        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        s_key = ndb.Key(Session, s_id, parent=c_key)
        data['key'] = s_key
        Session(**data).put()

        taskqueue.add(params={'speaker_email': request.speaker, 
            'wsck': request.websafeConferenceKey}, url = '/tasks/set_featured_speaker')
        return self._copySessionToForm(s_key.get())

    def _copySessionToForm(self, session):
        '''Copy relevant fields from Session to SessionForm.'''
        s_form = SessionForm()
        for field in s_form.all_fields():
            if hasattr(session, field.name):
                if field.name in ['date', 'startTime']:
                    setattr(s_form, field.name, str(getattr(session, field.name)))
                elif field.name == 'typeOfSession':
                    setattr(s_form, field.name, getattr(SessionType, getattr(session, field.name)))
                else:
                    setattr(s_form, field.name, getattr(session, field.name))
        setattr(s_form, 'websafeKey', session.key.urlsafe())
        s_form.check_initialized()
        return s_form


    @endpoints.method(SESSION_CREATE_REQUEST, SessionForm,
            path='session', http_method='POST', name='createSession')
    def createSession(self, request):
        '''Create new session'''
        return self._createSessionObject(request)

    @endpoints.method(CON_SESSION_GET_REQUEST, SessionForms,
            path='conference/sessions/{websafeConferenceKey}', http_method='GET',
            name='getConferenceSessions')
    def getConferenceSessions(self, request):
        '''Return all sessions in a conference'''
        c_key = ndb.Key(urlsafe=request.websafeConferenceKey)
        conf = c_key.get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        sessions = Session.query(ancestor=c_key)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(CON_SES_TYPE_GET_REQUEST, SessionForms,
            path='conference/sessions/query/type/{typeOfSession}', 
            http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        '''Return all sessions of a specified type'''
        c_key = ndb.Key(urlsafe=request.websafeConferenceKey)
        conf = c_key.get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        q = Session.query(ancestor=c_key)
        session_type = str(getattr(request, 'typeOfSession'))
        q = q.filter(Session.typeOfSession == session_type)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in q]
        )

    @endpoints.method(SES_SEPAKER_GET_REQUEST, SessionForms,
            path='session/querybuspeaker', http_method='POST',
            name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        '''Return all sessions of the speaker'''
        speaker_key = ndb.Key(Speaker, request.speaker)
        if not speaker_key.get():
            raise endpoints.NotFoundException(
                'No speaker found with id: %s' % request.speaker)
        q = Session.query()
        q = q.filter(Session.speaker == request.speaker)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in q]
        )

# - - - TASK2:Wishlist - - - - - - - - - - - - - - - - - - - -

    def _wishlistHandle(self, request, add=True):
        """
        Using the request to handle wishlist
        Returns:
          BooleanMessage: if add/remove is succuss
        Args:
          request: SES_REQUEST
          add: Bool, if is true add to wishlist else remove.
        """
        prof = self._getProfileFromUser()
        s_key = ndb.Key(urlsafe=request.sessionKey)
        session = s_key.get()
        retval = None
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % request.sessionKey)
        if add:
            wsck = s_key.parent().urlsafe()
            if wsck not in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You must register for the conference:%s first" % wsck)
            if request.sessionKey in prof.wishlist:
                raise ConflictException(
                    "You have already add this session to your wishlist")
            prof.wishlist.append(request.sessionKey)
            retval = True
        else:
            if  request.sessionKey in prof.wishlist:
                prof.wishlist.remove(request.sessionKey)
                retval = True
            else:
                retval = False

        prof.put()
        return BooleanMessage(data=retval)

    @endpoints.method(SES_REQUEST, BooleanMessage,
            path='session/add_whishlist', http_method='POST',
            name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        '''Add session to wishlist'''
        return self._wishlistHandle(request)

    @endpoints.method(SES_REQUEST, BooleanMessage,
            path='session/delete_wishlist', http_method='DELETE',
            name='deleteSessionInWishlist')
    def deleteSessionInWishlist(self, request):
        '''Removes the session from the user's whislist'''
        return self._wishlistHandle(request, add=False)

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='wishlist', http_method='GET', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        '''Get all the sessions in the user's wishlist'''
        prof = self._getProfileFromUser()
        wssks = prof.wishlist
        s_keys = [ndb.Key(urlsafe=wssk) for wssk in wssks]
        sessions = ndb.get_multi(s_keys)

        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )


# - - - TASK2: Two additional queries - - - - - - - - - - - - - - - - - - - -
    @endpoints.method(SessionHighlightsForm, SessionForms,
            path='session/highlights', http_method='GET', 
            name='getSessionsWithHighlights')
    def getSessionsWithHighlights(self, request):
        '''Get sessions in the list of highlights'''
        q = Session.query(Session.highlights.IN(request.highlights))
        return SessionForms(
            items=[self._copySessionToForm(session) for session in q]
        )

    @endpoints.method(SessionSpeakerFieldForm, SessionForms,
            path='session/speakerfield', http_method='GET',
            name='getSessionsWithSpeakerField')
    def getSessionsWithSpeakerField(self, request):
        '''Get sessions with the speaker's fields'''
        speakers = Speaker.query(Speaker.field.IN(request.fields)).fetch()
        if speakers == []:
            return SessionForms(items=[])
        speakers_email = [speaker.email for speaker in speakers]
        sessions = Session.query(Session.speaker.IN(speakers_email))
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='session/task3', http_method='POST',
            name='task3')
    def task3(self, request):
        '''
            This query is for the task3:Query Problem
            Args:
                have no input info
            Return:
                a list of sessions in which each session 
                    is not workshop and start before 7:00pm
        '''
        aim_time = time(19)
        sessions = Session.query(Session.startTime < aim_time)
        result_sessions = []
        result_sessions = [session for session in sessions if 
                                session.typeOfSession != 'WORKSHOP' and
                                session.startTime != None]
        return SessionForms(
            items=[self._copySessionToForm(session) for session in result_sessions]
        )

# - - - TASK4: Add a Task - - - - - - - - - - - - - - - - - - - -
    @staticmethod
    def _cacheFeaturedSpeaker(speaker_email, wsck):
        '''
         If there is more than one session by this speaker at this conference, 
            then assign the Featured Speaker to memcache
        Args: 
            speaker_email: The speaker's email
            wsck: the aimed conference's web safe url key
        '''
        # Fetch a list of Sessions at the provided Conference
        # that the Speaker is speaking at.
        s_key = ndb.Key(Speaker, speaker_email)
        speaker = s_key.get()
        c_key = ndb.Key(urlsafe=wsck)
        q = Session.query(ancestor=c_key)
        sessions = q.filter(Session.speaker == speaker_email).fetch()
        # if sesions count <= 1 break the function.
        if len(sessions) <= 1:
            return
        # Set the featured string for the speaker.
        featuredInfo = "| %s's sessions: %s" %(speaker.name ,','.join(session.name for session in sessions))
        cacheInfo = memcache.get(MEMCACHE_FEATUREDSPEAKER_KEY)
        featuredStr = ""
        # This tag is used to check if speaker is already in the memcache
        isChanged = False
        if not cacheInfo:
            featuredStr = "Featured Speakers:" + featuredInfo
            isChanged = True
        else:
            infos = cacheInfo.split('|',1)
            for (i, info) in enumerate(infos):
                if i == 0:
                    continue
                if speaker.name in info:
                    isChanged=True
                    infos[i] = featuredInfo[1:]
            featuredStr = '|'.join(infos)
        # If the speaker's info is not in the memcache, then append this str.
        if not isChanged:
            featuredStr += featuredInfo
        # Set memcache
        memcache.set(MEMCACHE_FEATUREDSPEAKER_KEY, featuredStr)

    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='featuredspeaker', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        '''Get featured speaker info'''
        featuredInfo = memcache.get(MEMCACHE_FEATUREDSPEAKER_KEY)
        if not featuredInfo:
            featuredInfo = ""
        return StringMessage(data=featuredInfo)

api = endpoints.api_server([ConferenceApi]) # register API
