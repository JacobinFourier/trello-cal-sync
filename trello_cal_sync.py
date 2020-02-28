
import datetime
import inspect
import json
import os.path
import pickle
import pprint

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from trello import TrelloClient


class Trello:

    def __init__(self, member, api_key, api_secret, token):
        self.trello = TrelloClient(api_key=api_key, api_secret=api_secret, token=token)

        self.member = member
        self.cards = []

        self.get_member_cards()


    def get_member_cards(self):
        member = self.trello.get_member(self.member)
        self.cards = member.fetch_cards()
        self.preprocess_cards()


    def preprocess_cards(self):
        # localize dates
        for c in self.cards:
            c['dateLastActivity'] = datetime.datetime.fromisoformat(c['dateLastActivity'].replace("Z", "+00:00")).astimezone()
            if c['due']:
                c['due'] = datetime.datetime.fromisoformat(c['due'].replace("Z", "+00:00")).astimezone()


    def get_done(self):
        """
        return the cards that are considered 'Done'
        """
        done = [c for c in self.cards if c['dueComplete']]
        done = sorted(done, key=lambda c: c['dateLastActivity'])
        return done


    def get_to_complete(self):
        """
        return the cards that are considered 'To Be Completed'. that means if it has a due date
        and it's not marked completed yet.
        """
        to_complete = [c for c in self.cards if not c['dueComplete'] and c['due'] is not None]
        to_complete = sorted(to_complete, key=lambda c: c['due'])
        return to_complete


    def get_missing_due_date(self):
        # cards should never be missing a due date
        missing_due_date = [c for c in self.cards if not c['dueComplete'] and c['due'] is None]
        missing_due_date = sorted(missing_due_date, key=lambda c: c['dateLastActivity'])
        return missing_due_date


    def output_to_file(self):
        """ for debugging """
        output = """
        <html>
        <head>
            <style>
                h1 {
                }
                table th {
                    text-align: left;
                }
                table td {
                    text-align: left;
                }
            </style>
        </head>
        <body>
        """

        output += "<h1>Done</h1>\n"
        output += "<table><thead><th>Est. Completion Date</th><th>Name</th></thead>\n"
        for card in self.get_done():
            output += "<tr><td>%s</td><td><a href='%s'>%s</a></td></tr>\n" % (card['dateLastActivity'].strftime("%c"), card['shortUrl'], card['name'])
        output += "</table>"

        output += "<h1>To Be Completed</h1>\n"
        output += "<table><thead><th>Due Date</th><th>Name</th></thead>\n"
        for card in self.get_to_complete():
            output += "<tr><td>%s</td><td><a href='%s'>%s</a></td></tr>\n" % (card['due'].strftime("%c"), card['shortUrl'], card['name'])
        output += "</table>"

        output += "<h1>Missing Due Date</h1>"
        output += "<table><thead><th>Last Updated</th><th>Name</th></thead>\n"
        for card in self.get_missing_due_date():
            output += "<tr><td>%s</td><td><a href='%s'>%s</a></td></tr>\n" % (card['dateLastActivity'].strftime("%c"), card['shortUrl'], card['name'])

        output += """
        </body>
        </html>
        """

        f = open("allcards.html", "w")
        f.write(output)
        f.close()


class TrelloJeff(Trello):
    """ jeff's custom class """
    pass


class Calendar:

    SCOPES = ['https://www.googleapis.com/auth/calendar']

    def __init__(self, name):
        self.service = self.get_service()

        response = self.service.calendarList().list().execute()
        matches = [cal for cal in response['items'] if cal['summary'] == name]
        if len(matches) == 0:
            msg = f"Couldn't find calendar with name: {name}"
            msg += ". Available calendars: " + [cal['summary'] for cal in response['items']].join(", ")
            raise Exception(msg)

        self.calendar_id = matches[0]['id']


    def get_service(self):
        """ adapted from quickstart docs """

        creds = None
        # The file token.pickle stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', self.SCOPES)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)

        service = build('calendar', 'v3', credentials=creds)

        return service


    def create_event(self, event):
        print(f"Creating event: {event['summary']}")
        self.service.events().insert(calendarId=self.calendar_id, body=event).execute()


    def update_event(self, event_id, event):
        print(f"Updating event: {event_id}")
        self.service.events().update(calendarId=self.calendar_id, eventId=event_id, body=event).execute()


    def get_all_events(self):
        all_events = []
        page_token = None
        while True:
            events = self.service.events().list(calendarId=self.calendar_id).execute()
            all_events += events['items']
            page_token = events.get('nextPageToken')
            if not page_token:
                break
        return all_events


    def delete_event(self, event_id):
        print(f"Deleting {event_id}")
        self.service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()


class Synchronizer:
    """ This is the glue that syncs trello w/ google calendar """

    def __init__(self, trello, calendar):
        self.trello = trello
        self.calendar = calendar


    def translate(self, card):
        """
        translate a trello card to a data structure representing an event that
        can be used w/ the google API
        """
        event = {
          'summary': 'DUE: ' + card['name'],
          # outlook doesn't pick up or display source.url, so put it in the description
          'description': card['shortUrl'],
          'source': {
            'url': card['shortUrl'],
          },
          'start': {
            'dateTime': str(card['due']).replace(' ', 'T')
          },
          'end': {
            'dateTime': str(card['due']).replace(' ', 'T')
          }
        }
        return event


    def execute(self):
        print("Fetching all calendar events")
        events = self.calendar.get_all_events()

        # remove cards that are Done b/c they clutter my calendar and are annoying
        for card in self.trello.get_done():
            to_delete = [e for e in events if e['source']['url'] == card['shortUrl']]
            for e in to_delete:
                print("Deleting done event from calendar")
                self.calendar.delete_event(e['id'])

        # remove events for cards that got deleted
        for event in events:
            card_exists = len([card for card in self.trello.cards if event['source']['url'] == card['shortUrl']]) > 0
            if not card_exists:
                print("Deleting event that no longer has a trello card")
                self.calendar.delete_event(event['id'])

        # create or update events for cards that need to be completed
        for card in self.trello.get_to_complete():

            to_update = [e for e in events if e['source']['url'] == card['shortUrl']]

            event_data_for_card = self.translate(card)

            if len(to_update) > 0:
                for e in to_update:
                    needs_update = \
                        e['start']['dateTime'] != event_data_for_card['start']['dateTime'] or \
                        e['summary'] != event_data_for_card['summary'] or \
                        e.get('description') != event_data_for_card.get('description')

                    if needs_update:
                        print("Updating calendar event w/ changed card info")
                        self.calendar.update_event(e['id'], event_data_for_card)
            else:
                self.calendar.create_event(event_data_for_card)


def read_config():
    """
    read the config.json file and return it as a python data structure,
    substituting class names w/ class objects for the relevant args
    """
    config = json.load(open("config.json", "r"))

    for class_arg in [key for key in config.keys() if key.endswith("_class")]:
        classname = config[class_arg]
        try:
            class_ = eval(classname)
        except:
            raise Exception(f"Couldn't find the class specifed in arg {class_arg} with name '{classname}'")

        if not inspect.isclass(class_):
            raise Exception(f"{classname} isn't a class, fix your config.json")

        config[class_arg] = class_
    return config


def sync(trello, google_calendar, trello_class=Trello, calendar_class=Calendar, synchronizer_class=Synchronizer):
    """
    perform the sync. this is the main entry point.
    """

    trello_options = trello

    trello = trello_class(**trello_options)

    calendar = calendar_class(**google_calendar)

    synchronizer = synchronizer_class(trello, calendar)

    synchronizer.execute()


def debug_trello():
    config = read_config()
    trello = Trello(**config['trello'])
    trello.output_to_file()


if __name__ == '__main__':
    config = read_config()
    sync(**config)
