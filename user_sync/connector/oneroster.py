# from __future__ import print_function
import json
import logging
import re

import classlink_oneroster
import requests


# Github: https://github.com/vossen-adobe/classlink
# PyPI: https://pypi.org/project/classlink-oneroster/

def get_connector(options):
    platform = options['platform']
    if platform == 'classlink':
        return ClasslinkConnector(options)
    elif platform == 'clever':
        return CleverConnector(options)

    raise NotImplementedError("No module for " + platform +
                              " was found. Supported are: [classlink, clever]")


def decode_string(string):
    try:
        decoded = string.decode()
    except:
        decoded = str(string)
    return decoded.lower().strip()


#
#
#
#
#
#

class ClasslinkConnector():
    """ Starts connection and makes queries with One-Roster API"""

    def __init__(self, options):
        self.logger = logging.getLogger("classlink")
        self.host_name = options.get('host')
        self.client_id = options.get('client_id')
        self.client_secret = options.get('client_secret')
        self.key_identifier = options.get('key_identifier')
        self.max_users = options.get('max_user_limit')
        self.page_size = str(options.get('page_size'))
        self.classlink_api = classlink_oneroster.ClasslinkAPI(self.client_id, self.client_secret)

    def get_users(self,
                  group_filter=None,  # Type of group (class, course, school)
                  group_name=None,  # Plain group name (Math 6)
                  user_filter=None,  # Which users: users, students, staff
                  request_type=None,  # Determines which logic is used (see below)
                  ):

        results = []
        if group_filter == 'courses':
            key_id = self.execute_actions('courses', group_name, self.key_identifier, 'key_identifier')
            if key_id.__len__() == 0:
                return results
            list_classes = self.execute_actions(group_filter, user_filter, key_id, 'course_classlist')
            for each_class in list_classes:
                results.extend(self.execute_actions('classes', user_filter, each_class, 'mapped_users'))
        elif request_type == 'all_users':
            results.extend(self.execute_actions(None, user_filter, None, 'all_users'))
        else:
            key_id = self.execute_actions(group_filter, None, group_name, 'key_identifier')
            if key_id.__len__() == 0:
                return results
            results.extend(self.execute_actions(group_filter, user_filter, key_id, 'mapped_users'))
        return results

    def execute_actions(self, group_filter, user_filter, identifier, request_type):
        result = []
        if request_type == 'all_users':
            url_request = self.construct_url(user_filter, None, '', None)
            result = self.make_call(url_request, 'all_users', None)
        elif request_type == 'key_identifier':
            if group_filter == 'courses':
                url_request = self.construct_url(user_filter, identifier, 'course_classlist', None)
                result = self.make_call(url_request, 'key_identifier', group_filter, user_filter)
            else:
                url_request = self.construct_url(group_filter, identifier, 'key_identifier', None)
                result = self.make_call(url_request, 'key_identifier', group_filter, identifier)
        elif request_type == 'mapped_users':
            base_filter = group_filter if group_filter == 'schools' else 'classes'
            url_request = self.construct_url(base_filter, identifier, request_type, user_filter)
            result = self.make_call(url_request, 'mapped_users', group_filter, group_filter)
        elif request_type == 'course_classlist':
            url_request = self.construct_url("", identifier, 'users_from_course', None)
            result = self.make_call(url_request, request_type, group_filter)
        return result

    def construct_url(self, base_string_seeking, id_specified, request_type, users_filter):
        if request_type == 'course_classlist':
            url_ender = 'courses/?limit=' + self.page_size + '&offset=0'
        elif request_type == 'users_from_course':
            url_ender = 'courses/' + id_specified + '/classes?limit=' + self.page_size + '&offset=0'
        elif users_filter is not None:
            url_ender = base_string_seeking + '/' + id_specified + '/' + users_filter + '?limit=' + self.page_size + '&offset=0'
        else:
            url_ender = base_string_seeking + '?limit=' + self.page_size + '&offset=0'
        return self.host_name + url_ender

    def make_call(self, url, request_type, group_filter, group_name=None):
        user_list = []
        key = 'first'
        while key is not None:
            if key == 'first':
                response = self.classlink_api.make_roster_request(url)
            else:
                response = self.classlink_api.make_roster_request(response.links[key]['url'])
            if not response.ok:
                raise ValueError('Non Successful Response'
                                 + '  ' + 'status:' + str(response.status_code) + '  ' + 'message:' + str(response.reason))
            if request_type == 'key_identifier':
                other = 'course' if group_filter == 'courses' else 'classes'
                name_identifier, revised_key = ('name', 'orgs') if group_filter == 'schools' else ('title', other)
                for entry in json.loads(response.content).get(revised_key):
                    if decode_string(entry[name_identifier]) == decode_string(group_name):
                        try:
                            key_id = entry[self.key_identifier]
                        except ValueError:
                            raise ValueError('Key identifier: ' + self.key_identifier + ' not a valid identifier')
                        user_list.append(key_id)
                        return user_list[0]
            elif request_type == 'course_classlist':
                for ignore, entry in json.loads(response.content).items():
                    user_list.append(entry[0][self.key_identifier])
            else:
                for ignore, users in json.loads(response.content).items():
                    user_list.extend(users)
            if key == 'last' or int(response.headers._store['x-count'][1]) < int(self.page_size):
                break
            key = 'next' if 'next' in response.links else 'last'

        if not user_list:
            self.logger.warning("No " + request_type + " for " + group_filter + "  " + group_name)

        return user_list


#
#
#
#   Clever
#
#
#
#


class CleverConnector():

    def __init__(self, options):

        self.logger = logging.getLogger("clever")
        self.client_id = options.get('client_id')
        self.client_secret = options.get('client_secret')
        self.max_users = options.get('max_user_limit')
        self.match = options.get('match') or 'name'
        self.page_size = options.get('page_size') or 10000
        self.access_token = options.get('access_token')
        self.host = options.get('host') or 'https://api.clever.com/v2.1/'
        self.max_users = None if self.max_users <= 0 else self.max_users

        if not self.access_token:
            self.authenticate()

        self.auth_header = {"Authorization": "Bearer " + self.access_token}

    def authenticate(self):
        try:
            auth_resp = requests.get("https://clever.com/oauth/tokens", auth=(self.client_id, self.client_secret))
            self.access_token = json.loads(auth_resp.content)['data'][0]['access_token']
        except ValueError:
            raise LookupError("Authorization attempt failed...")

    def get_users(self,
                  group_filter=None,  # Type of group (class, course, school)
                  group_name=None,  # Plain group name (Math 6)
                  user_filter=None,  # Which users: users, students, staff
                  **kwargs
                  ):

        results = []
        calls = self.translate(group_filter=group_filter, user_filter=user_filter)
        if group_filter == 'courses':
            results = self.get_users_for_course(name=group_name, user_filter=user_filter)
        elif group_filter:
            for c in calls:
                for i in self.get_primary_key(group_filter, group_name):
                    results.extend(self.make_call(c.format(i), users=True))
        else:
            [results.extend(self.make_call(c, users=True)) for c in calls]

        for user in results:
            user['givenName'] = user['name'].get('first')
            user['familyName'] = user['name'].get('last')
            user['middleName'] = user['name'].get('middle')
        return results

    def make_call(self, url, users=False):

        next = ""
        collected_objects = []
        while True:
            try:
                response = requests.get(url + '?limit=' + str(self.page_size) + next, headers=self.auth_header)
                new_objects = json.loads(response.content)['data']
                if new_objects:
                    collected_objects.extend(new_objects)
                    next = '&starting_after=' + new_objects[-1]['data']['id']
                    if self.max_users and users and len(collected_objects) > self.max_users:
                        collected_objects = collected_objects[0:self.max_users]
                        break
                else:
                    break
            except Exception as e:
                raise e
        extracted_objects = [o['data'] for o in collected_objects]
        return extracted_objects

    def get_primary_key(self, type, name):
        if self.match == 'id':
            return name

        url = self.translate(None, type)[0]
        objects = self.make_call(url)
        id_list = []

        for o in objects:
            try:
                if decode_string(o[self.match]) == decode_string(name):
                    id_list.append(o['id'])
            except KeyError:
                self.logger.warning("No property: '" + self.match +
                                    "' was found on " + type.rstrip('s') + " for entity '" + name + "'")
                break
        if not id_list:
            self.logger.warning("No objects found for " + type + ": " + name)
        return id_list

    def get_sections_for_course(self, name):
        id_list = self.get_primary_key('courses', name)
        sections = []
        for i in id_list:
            call = self.translate('courses', 'sections')[0].format(i)
            sections.extend(self.make_call(call))
        if not sections:
            self.logger.warning("No sections found for course '" + name + "'")
            return []
        else:
            return [s['id'] for s in sections]

    def get_users_for_course(self, name, user_filter='users'):
        urls = self.translate('sections', user_filter)
        sections = self.get_sections_for_course(name)
        user_list = []
        for s in sections:
            for c in urls:
                user_list.extend(self.make_call(c.format(s)))
        if not user_list:
            self.logger.warning("No users found for course '" + name + "'")
        return user_list

    def translate(self, group_filter, user_filter):

        # if group_filter not in ['sections, courses, schools'] or user_filter not in ['students, users, teachers, sections']:
        #     raise ValueError("Unrecognized method request: 'get_" + user_filter + "_for_" + group_filter + "'")

        group_filter = group_filter + "/{}/" if group_filter else ''
        user_filter = user_filter if user_filter else ''
        url = self.host + group_filter + user_filter

        if user_filter == 'users':
            return [url.replace(user_filter, 'students'), url.replace(user_filter, 'teachers')]
        else:
            return [url]