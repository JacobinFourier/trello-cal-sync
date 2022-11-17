
import datetime
import inspect
import json
import os.path
import pickle
import pprint
import time

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from trello import TrelloClient
from google.oauth2 import service_account



class Trello:

    # cache shared across all instances of this class
    list_cache = {}

    def __init__(self, member, api_key, api_secret, token):
        self.trello = TrelloClient(api_key=api_key, api_secret=api_secret)

        self.member = member
        self.cards = []

        print(f"Fetching cards for {self.member}")
        self.get_member_cards()


    def get_member_cards(self):
        member = self.trello.get_member(self.member)
        self.cards = member.fetch_cards()
        self.preprocess_cards()


    def get_list_name(self, list_id):
        """ cache trello List objects """
        if list_id not in self.list_cache:
            list_data = self.trello.get_list(list_id)

            # ensure we stay under 100 hits per 10 sec period limit
            time.sleep(0.15)

            self.list_cache[list_id] = list_data
        return self.list_cache[list_id].name


    def date_str_to_datetime_obj(self, date_str):
        # trim off miscroseconds and Z char, and set to UTC
        trimmed = date_str[0:-5] + "+0000"
        return datetime.datetime.strptime(trimmed, "%Y-%m-%dT%H:%M:%S%z").astimezone()


    def preprocess_cards(self):
        for c in self.cards:
            # store actual list name
            c['listName'] = self.get_list_name(c['idList'])

            # localize dates
            c['dateLastActivity'] = self.date_str_to_datetime_obj(c['dateLastActivity'])
            if c['due']:
                c['due'] = self.date_str_to_datetime_obj(c['due'])


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

    def __init__(self, id=None, name=None, auth_type="service_account"):

        self.auth_type = auth_type
        self.service = self.get_service()

        if id:
            self.calendar_id = id
        else:
            # WARNING: calendarList endpoint doesn't seem to work with the service account.
            # This will fail if you use that method and don't provide a calendar id.
            response = self.service.calendarList().list().execute()
            matches = [cal for cal in response['items'] if cal['summary'] == name]
            if len(matches) == 0:
                msg = f"Couldn't find calendar with name: {name}"
                msg += ". Available calendars: " + ", ".join([cal['summary'] for cal in response['items']])
                raise Exception(msg)

            self.calendar_id = matches[0]['id']


    def get_service(self):
        """ adapted from quickstart docs """

        creds = None

        if self.auth_type == "service_account":
            
            creds = service_account.Credentials.from_service_account_file(r'C:\Users\vladi\Documents\GitHub\trello-cal-sync\service-account.json', scopes=self.SCOPES)
        elif self.auth_type == "oauth":
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
                        r'C:\Users\vladi\Documents\GitHub\trello-cal-sync\config.json', self.SCOPES)
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

        in_progress = ""
        if "in progress" in card['listName'].lower() or \
            "doing" in card['listName'].lower():
            in_progress = "(IN PROGRESS) "

        summary = 'DUE: ' + in_progress + card['name']

        event = {
          'summary': summary,
          # outlook doesn't pick up or display source.url, so put it in the description
          'description': card['shortUrl'],
          # note that service account can't seem to read 'source' fields
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


    def dates_equal(self, date1_str, date2_str):
        """
        returns True if the two date strings are conceptually the same time
        """
        d1 = datetime.datetime.strptime(date1_str, "%Y-%m-%dT%H:%M:%S%z")
        d2 = datetime.datetime.strptime(date2_str, "%Y-%m-%dT%H:%M:%S%z")
        return d1==d2


    def event_needs_update(self, existing_event, event_data_from_card):
        """
        compares existing calendar event and new event data structure
        generated from trello card, and returns True if the event needs
        to be updated
        """
        return not self.dates_equal(existing_event['start']['dateTime'], event_data_from_card['start']['dateTime']) or \
            existing_event['summary'] != event_data_from_card['summary'] or \
            existing_event.get('description') != event_data_from_card.get('description')


    def execute(self):
        print("Fetching all calendar events")
        events = self.calendar.get_all_events()

        # remove cards that are Done b/c they clutter my calendar and are annoying
        for card in self.trello.get_done():
            to_delete = [e for e in events if e['description'] == card['shortUrl']]
            for e in to_delete:
                print("Deleting done event from calendar")
                self.calendar.delete_event(e['id'])

        # remove events for cards that got deleted
        for event in events:
            card_exists = len([card for card in self.trello.cards if event['description'] == card['shortUrl']]) > 0
            if not card_exists:
                print("Deleting event that no longer has a trello card")
                self.calendar.delete_event(event['id'])

        # create or update events for cards that need to be completed
        for card in self.trello.get_to_complete():

            existing_events = [e for e in events if e['description'] == card['shortUrl']]

            event_data_from_card = self.translate(card)

            if len(existing_events) > 0:
                for existing_event in existing_events:
                    needs_update = self.event_needs_update(existing_event, event_data_from_card)

                    if needs_update:
                        print("Updating calendar event w/ changed card info")
                        self.calendar.update_event(existing_event['id'], event_data_from_card)
            else:
                self.calendar.create_event(event_data_from_card)


def read_config():
    """
    read the config.json file and return it as a python data structure,
    substituting class names w/ class objects for the relevant args
    """
    config = json.load(open(r"C:\Users\vladi\Documents\GitHub\trello-cal-sync\config.json", "r"))

    for sync_item in config["sync"]:
        for class_arg in [key for key in sync_item.keys() if key.endswith("_class")]:
            classname = sync_item[class_arg]
            try:
                class_ = eval(classname)
            except:
                raise Exception(f"Couldn't find the class specifed in arg {class_arg} with name '{classname}'")

            if not inspect.isclass(class_):
                raise Exception(f"{classname} isn't a class, fix your config.json")

            sync_item[class_arg] = class_
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
    for sync_item in config["sync"]:
        start = time.time()
        try:
            sync(**sync_item)
        except Exception as e:
            # if script fails b/c of trello API limit, wait a bit
            # so next sync doesn't fail for same reason
            time.sleep(11)

            print(f"Error while syncing {sync_item['trello']['member']}: {e}")
            print("Continuing with next sync item")
        elapsed = time.time() - start
        print(f"Sync took {elapsed}s")
