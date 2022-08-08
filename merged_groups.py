""" py 3.9
sync a set of course groups based on merged course enrollments
developed by jeff.kelley@anthology.com

ANTHOLOGY MAKES NO REPRESENTATIONS OR WARRANTIES ABOUT THE SUITABILITY
OF THE SOFTWARE, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
TO THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE, OR NON-INFRINGEMENT. ANTHOLOGY SHALL NOT BE LIABLE FOR ANY
DAMAGES SUFFERED BY LICENSEE AS A RESULT OF USING, MODIFYING OR
DISTRIBUTING THIS SOFTWARE OR ITS DERIVATIVES.

 
Stuff to do:
 - Remove import modules not used
 - Adopt known methods to handle auth token near expiration
 - Implement a proper logging method
 - Address paging for calls which might excede 100 records (get course users)


"""

import requests
import json
import datetime
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.poolmanager import PoolManager
import ssl
import sys
import csv
import pandas as pd
import argparse
import configparser
import pprint


pp = pprint.PrettyPrinter(depth=6)

# Current date/time in the format YYYMMDD-hhmm  eg.  20190726-1850-45
timeStamp=datetime.datetime.now().strftime("%Y%m%d-%H%M")

#### check for whitespace ####
def has_spaces(*strings):
    counter=0
    for a in strings:
        for b in a:        
            if (a.isspace()) == True:
                sys.exit('You have a space in the string: ' + a)
    return False

""" Bypassing properties file for testing:

# parse the arguments in the command line 
parser = argparse.ArgumentParser(description='COURSE ID and properties file.')
parser.add_argument("BbCourseID", help="The Learn course Id value")
parser.add_argument("Properties_File", help="The attendance properties file")

args = parser.parse_args()
COURSEID = args.BbCourseID
propFile = args.Properties_File

# read the properties file into "config" container
config = configparser.ConfigParser()
config.read(propFile)

# setting variables from properties file
KEY = config.get('properties', 'KEY')
SECRET = config.get('properties', 'SECRET')
HOST = 'https://' + config.get('properties', 'HOST')
RESULTLIMIT = config.get('properties', 'RESULTLIMIT')

"""


KEY = "YOURKEY"
SECRET = "YOURSECRET"
HOST = "https://demo.blackboard.com"
RESULTLIMIT = 100
COURSEID = "YOURCOURSEID"


#### logging class #########
class Logger(object):
    def __init__(self):
        self.terminal = sys.stdout
        self.log = open("module.log", "a")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)  

    def flush(self):
        #this flush method is needed for python 3 compatibility.
        #this handles the flush command by doing nothing.
        #you might want to specify some extra behavior here.
        pass    

sys.stdout = Logger()


#########################
# do authentication and return oAuth object with session token
def get_token():

    oAuth = {
        "key" : KEY,
        "secret" : SECRET,
        "host" : HOST
    }
  
    AUTHDATA = {
      'grant_type': 'client_credentials'
    }

    r = requests.post(HOST + '/learn/api/public/v1/oauth2/token', data=AUTHDATA, auth=(KEY, SECRET))

    if r.status_code == 200:  #success
        parsed_json = json.loads(r.text)  #read the response into dictionary
        oAuth["token"] = parsed_json['access_token'] 
        oAuth["authStr"] = 'Bearer ' + oAuth["token"]
        #convert expires in to expires at
        auth_exp = datetime.datetime.now() + datetime.timedelta(seconds=int(parsed_json['expires_in']))
        auth_exp_strng = auth_exp.strftime('%Y/%m/%d %H:%M:%S.%f')
        oAuth["token_expires"] = auth_exp_strng
        print("Token " + oAuth["token"] + " Expires at " + oAuth["token_expires"])

    else:  #failed to authenticate
      print ('Failed to authenticate: ' + r.text)
      sys.exit()

    return oAuth


##########################
# check if we need a new token
# not used yet - probably don't for 1 course at a time.

def is_token_exp(oAuth):

    expired = True
    exp_datetime = datetime.datetime.strptime(oAuth["token_expires"],'%Y/%m/%d %H:%M:%S.%f')

    if exp_datetime < datetime.datetime.now():
        #print('[auth:is_token_exp()] Token Expired at ' + oAuth["token_expires"])
        expired = True

    else:
        #print('[auth:is_token_exp()] Token will expire at ' + oAuth["token_expires"])
        expired = False

    return expired


#########################
# check if course is parent and get stuff about it
# returns a dictionary object for the parent course
def get_parent(courseId, oAuth):

    endpoint="/learn/api/public/v3/courses/"
    courseKey="courseId:" + courseId
    params="?fields=id,courseId,externalId,name,hasChildren"

    path = endpoint + courseKey + params
    #print("Get :" + path)
    
    getParent = requests.get(HOST + path, headers={'Authorization':oAuth["authStr"]})
    if getParent.status_code != 200:
        print ('Error getting course: ' + courseId)
        print ('Status: ' + str(getParent.status_code))
        sys.exit()
    parent = json.loads(getParent.text)
    #print (course)
    if parent["hasChildren"]:
        print(courseId + " is a Parent Course... continue")
    else:
        print(courseId + " has no Children... exit")
        sys.exit()

    return parent

#########################
# get info about children
# don't bother paging - only a problem if more children then RESULTLIMIT
# returns a list of dictionaires with a list element for a child course
def get_children(courseId, oAuth):

    endpoint="/learn/api/public/v1/courses/"
    courseKey="courseId:" + courseId
    params="/children?expand=childCourse&fields=id,childCourse.externalId,childCourse.name,childCourse.courseId"

    path = endpoint + courseKey + params
    #print("Get : " + path)
    
    getChildren = requests.get(HOST + path, headers={'Authorization':oAuth["authStr"]})
    if getChildren.status_code != 200:
        print ('Error getting children for course: ' + courseId)
        print ('Status: ' + str(getChildren.status_code))
        sys.exit()

    response = json.loads(getChildren.text)
    results = response["results"]
    #print(results)

    #initialize list
    children = []

    #flattent dict and add to list
    for c in results:
        child = {}
        child["externalId"] = c["childCourse"]["externalId"]
        child["name"] = c["childCourse"]["name"]
        child["courseId"] = c["childCourse"]["courseId"]
        child["id"] = c["id"]

        children.append(child.copy())

    print("Number of children: "+ str(len(children)))

    return children


#########################
# build the courseList
# returns a list of dictionaries with list element for parent and each child course
def build_course_list(parent, children):
    courseList = []
    courseList.append(parent.copy())
    courseList.extend(children)
    #print(courseList)
    return courseList


#####################
# get or create merge group set
# returns a string for the set id (pk)
def sync_group_set(parent, oAuth):

    ext_id_suffix = "_auto_group_set"

    endpoint="/learn/api/public/v2/courses/"
    courseKey="courseId:" + parent['courseId']
    params="/groups/sets/"
    setKey= "externalId:" + parent['externalId']+ ext_id_suffix
    
    #see if set already exists and get id (pk) if it does
    path = endpoint + courseKey + params + setKey
    #print("Set GET :" + path)
    getSet = requests.get(HOST + path, headers={'Authorization':oAuth["authStr"]})

    if getSet.status_code == 200:
        #it exists
        set = json.loads(getSet.text)
        groupSetId = set["id"]
        print("The group set exists for course: " + parent["courseId"] + ". The set id is " + groupSetId)
        return groupSetId

    elif getSet.status_code == 404:
        #need to create it
        body = {
            "externalId": parent["externalId"]+ ext_id_suffix,
            "name": "Automated Child Merged Groups",
            "availability": {
                "available": "No"
                },
            "enrollment": {
                "type": "InstructorOnly"
                }
            }
        #print(body)
        path = endpoint + courseKey + params
        #print("Set POST :" + path)
        createSet = requests.post(HOST + path, headers={'Authorization':oAuth["authStr"]},json = body)
        if createSet.status_code != 201:
            print ('Error creating group set in course: ' + parent['courseId'])
            print ('Status: ' + str(createSet.status_code))
            sys.exit()
        set = json.loads(createSet.text)
        groupSetId = set["id"]
        print("Created the group set for course:  " + parent["courseId"] + ". The set id is " + groupSetId)
        return groupSetId
    
    else:
        print ('Error syncing the group set in : ' + parent["courseId"])
        print ('Status: ' + str(getSet.status_code))
        sys.exit()


###################
#get the list of groups in the set
def build_group_list(courseId,groupSetId, oAuth):
    
    endpoint= "/learn/api/public/v2/courses/"
    courseKey= "courseId:" + courseId
    params= "/groups/sets/"
    setKey= groupSetId
    params2= "/groups"
    fields = "?fields=id,name,externalId,description,availability.available,enrollment.type,groupSetId"

    path = endpoint + courseKey + params + setKey + params2 + fields
    #print(path)
    getGroups = requests.get(HOST + path , headers={'Authorization':oAuth["authStr"]})
    if getGroups.status_code != 200:
        print ('Error getting groups for course: ' + courseId)
        print ('Status: ' + str(getGroups.status_code))
        sys.exit()

    response = json.loads(getGroups.text)
    groups = response["results"]
    #print(groups)
    return groups


#############
# add or remove groups based on courseList
# course.externalId = group.externalId
def sync_groups(courseId, groupsList, courseList, groupSetId, oAuth):

    for g in groupsList:
        for c in courseList:
            if g["externalId"] == c["externalId"]:
                g["crsId"] = c["id"]
                c["grpId"] = g["id"]

    for c in courseList:
        if "grpId" not in c:
            create_group(c,courseId,groupSetId,oAuth)

    for g in groupsList:
        if "crsId" not in g:
            delete_group(g,courseId,oAuth)


#########
#create a group in the course/set
def create_group(c, courseId, groupSetId, oAuth):
    
    endpoint= "/learn/api/public/v2/courses/"
    courseKey= "courseId:" + courseId
    params= "/groups/sets/"
    setKey= groupSetId
    params2= "/groups/"

    path = endpoint + courseKey + params + setKey + params2

    body = {
        "externalId": c["externalId"],
        "name": c["courseId"],
        "description": "<p>This is the group for users enrolled in the child course : " + c["name"] + "</p>",
        "availability": {
            "available": "No"
            },
        "enrollment": {
            "type": "InstructorOnly"
            }
        }

    createGroup = requests.post(HOST + path, headers={'Authorization':oAuth["authStr"]},json = body)
    if createGroup.status_code !=201:
        print ('Error creating group ' + c["courseId"] + ' in course: ' + courseId)
        print ('Status: ' + str(createGroup.status_code))
        print (json.loads(createGroup.text))
        sys.exit()
    thisGroup = json.loads(createGroup.text)   
    print("Created group " + thisGroup["name"] + ". The group id is " + thisGroup["id"])


#########
# delete a group in the course
def delete_group(g,courseId,oAuth):

    endpoint= "/learn/api/public/v2/courses/"
    courseKey= "courseId:" + courseId
    params= "/groups/"
    groupKey= g["id"]

    path = endpoint + courseKey + params + groupKey

    deleteGroup = requests.delete(HOST + path, headers={'Authorization':oAuth["authStr"]})
    print(deleteGroup)
    if deleteGroup.status_code !=204:
        print ('Error deleting group ' + g["externalId"] + ' in course: ' + courseId)
        print ('Status: ' + str(deleteGroup.status_code))
        sys.exit()
    print("Deleted the group " + g["externalId"])



#######################
# return a courseRoster list of dictionaries from parent course

def get_course_roster (parent, courseList, oAuth):
    courseId = parent["courseId"]
    
    endpoint="/learn/api/public/v1/courses/"
    courseKey="courseId:" + courseId
    params="/users?expand=user&fields=id,userId,courseRoleId,childCourseId,user.userName,availability.available"

    path = endpoint + courseKey + params
    #print(path)
    
    getEnrollments = requests.get(HOST + path, headers={'Authorization':oAuth["authStr"]})
    if getEnrollments.status_code != 200:
        print ('Error getting enrollments for course: ' + courseId)
        print ('Status: ' + str(getEnrollments.status_code))
        sys.exit()
    response = json.loads(getEnrollments.text)
    enrollments = response["results"]
    print("Number of enrollments: "+ str(len(enrollments)))

    roster = []
    for e in enrollments:
        u = {}
        u["userId"] = e["userId"]
        u["userName"] = e["user"]["userName"]
        u["available"] = e["availability"]["available"]
        u["courseRoleId"] = e["courseRoleId"]

        if 'childCourseId' not in e:  #enrollment in parent course only
            u["externalCourseId"] = parent["externalId"]

        else:  #lookup externalId from child course
            for c in courseList:
                if c["id"] == e["childCourseId"]:
                    u["externalCourseId"] = c["externalId"]

        roster.append(u.copy())
        
    #pp.pprint(roster)
    return roster

#################################
## Build a group membership object from members in groups in a set
def get_groups_roster(parent,groupSetId,oAuth):
    courseId = parent["courseId"]

    groupRoster = []
    #refresh groupsList
    groupsList = build_group_list(courseId, groupSetId, oAuth)
    for g in groupsList:
        endpoint="/learn/api/public/v2/courses/"
        courseKey="courseId:" + courseId
        params= "/groups/"
        groupKey= g["id"]
        params2= "/users/"

        path = endpoint + courseKey + params + groupKey + params2

        getGroupMems = requests.get(HOST + path, headers={'Authorization':oAuth["authStr"]})
        if getGroupMems.status_code != 200:
            print ('Error getting members for group: ' + g["name"])
            print ('Status: ' + str(getGroupMems.status_code))
            sys.exit()
    
        response = json.loads(getGroupMems.text)
        members = response["results"]
        for m in members:
            m["externalGroupId"] = g["externalId"]
            m["groupId"] = g["id"]
        
        groupRoster.extend(members)

    #pp.pprint(groupRoster)
    return groupRoster



#################################
## Build and execute an action plan for adding/removing/moving users in groups
def sync_groupset_members(parent, courseRoster, groupsRoster, oAuth):
    courseId = parent["courseId"]
    actionPlan = []  #doing it this way so I can see plan before it executes

    for e in courseRoster:
        ap = {}  #initiate the actionplan entry

        if e["courseRoleId"] != "Student":
            e["inGroup"] = "n"
            ap["action"] = "donothing"
            ap["comment"] = "Only students can be in groups."
            ap.update(e)
        else:
            for m in groupsRoster:
                if e["userId"] == m["userId"]:  #match on userId
                    e["inGroup"] = "y"
                    if e["externalCourseId"] == m["externalGroupId"]:  #match course/group external ids
                        ap["action"] = "donothing"
                        ap["comment"] = "User is in the correct group."
                        ap.update(e)
                    else: #course and group don't match
                        ap["action"] = "move"
                        ap["comment"] = "User is in the wrong group."
                        ap["delGroup"] = m["externalGroupId"]  #remove from this group
                        ap.update(e)

        if ap:
            actionPlan.append(ap.copy())

    for e in courseRoster:
        ap = {}  #initiate the actionplan entry
        if "inGroup" not in e:
            ap["action"] = "add"
            ap["comment"] = "User in no group."
            ap.update(e)
            
        if ap:
            actionPlan.append(ap.copy())

    #pp.pprint(actionPlan)

    ### execute the plan

    for a in actionPlan:
        if a["action"] == "add":
            print("Adding user " + a["userName"] + " to group " + a["externalCourseId"])
            group_mem_action(courseId,a["userName"],a["externalCourseId"],"add")
        elif a["action"] == "move":
            print("Moving user " + a["userName"] +" from group " + a["delGroup"] + " to group " + a["externalCourseId"])
            group_mem_action(courseId,a["userName"],a["delGroup"],"remove")
            group_mem_action(courseId,a["userName"],a["externalCourseId"],"add")
        else:
            print("Doing nothing with " + a["userName"])


#################################
## add and remove group members
def group_mem_action(courseId,userName,externalGroupId,action):

    endpoint= "/learn/api/public/v2/courses/"
    courseKey= "courseId:" + courseId
    params= "/groups/"
    groupKey= "externalId:" + externalGroupId
    params2= "/users/"
    userKey= "userName:" + userName

    path = endpoint + courseKey + params + groupKey + params2 + userKey
    print(path)
    if action == "add":
        userAction = requests.put(HOST + path, headers={'Authorization':oAuth["authStr"]})
    elif action == "remove":
        userAction = requests.delete(HOST + path, headers={'Authorization':oAuth["authStr"]})


    if userAction.status_code == 201:
        print ("User added")
    elif userAction.status_code == 204:
        print ("User removed")
    else:
        print ('Error moving group member for course: ' + courseId)
        print ('Status: ' + str(userAction.status_code))
        sys.exit()


    

#################################
## START THE SCRIPT ###

#authenticate
oAuth = get_token()

#check if merged pareent, if yess get attributes
parent = get_parent(COURSEID, oAuth)

#get attributes from merged child courses
children = get_children(COURSEID, oAuth)

#combine parent and children into a list
courseList = build_course_list(parent,children)

#get or create the group set and store the id
groupSetId = sync_group_set(parent, oAuth)

#get groups as a list
groupsList = build_group_list(COURSEID, groupSetId, oAuth)

#add or remove groups based on courseList
sync_groups(COURSEID, groupsList, courseList, groupSetId, oAuth) 

#get parent course roster
cousreRoster = get_course_roster(parent, courseList, oAuth)

#get group members
groupsRoster = get_groups_roster(parent, groupSetId, oAuth)

#add and remove group members based on child course enrollments
sync_groupset_members(parent, cousreRoster, groupsRoster, oAuth) 



