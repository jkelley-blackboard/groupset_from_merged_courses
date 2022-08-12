""" py 3.9
sync a set of course groups based on merged course enrollments
developed by jeff.kelley@anthology.com

ANTHOLOGY MAKES NO REPRESENTATIONS OR WARRANTIES ABOUT THE SUITABILITY
OF THE SOFTWARE, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
TO THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE, OR NON-INFRINGEMENT. ANTHOLOGY SHALL NOT BE LIABLE FOR ANY
DAMAGES SUFFERED BY LICENSEE AS A RESULT OF USING, MODIFYING OR
DISTRIBUTING THIS SOFTWARE OR ITS DERIVATIVES.


usage = group_sync.py courseId properties_file

 
Stuff to do:
 - Handle paging for more than RESULTLIMIT records
      - 1st priority = parent course enrollments
      - 2nd priority = group memberships


"""

import requests
import json
import datetime
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.poolmanager import PoolManager
import sys
import pandas as pd
import logging
import argparse
import configparser


# parse the arguments in the command line 
parser = argparse.ArgumentParser(description='COURSE ID and properties file.')
parser.add_argument("BbCourseID", help="The Learn course Id value")
parser.add_argument("Properties_File", help="The properties file")

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
LOGLEVEL = config.get('properties', 'LOGLEVEL')


#logging level
logging.basicConfig(format='%(asctime)s| %(module)s: %(funcName)s| %(levelname)s: %(message)s', level=logging.INFO)
logger = logging.getLogger()
logger.setLevel(LOGLEVEL)


#################################
## MAIN SCRIPT ###
def main():

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



#####FUNCTIONS############

#########
## until paging is implemented
def check_for_paging(response_json):
    if "paging" in response_json:
        logging.critical("There are more than " + RESULTLIMIT + " records in the response. Paging not yet supported here....exiting.")
        sys.exit()

#########################
## do authentication and return oAuth object with session token
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
        logging.info("Token " + oAuth["token"] + " Expires at " + oAuth["token_expires"])

    else:  #failed to authenticate
      logging.critical('Failed to authenticate: ' + r.text)
      sys.exit()

    return oAuth


##########################
# check if we need a new token
# not used yet - probably don't for 1 course at a time.
# before any request you can use "oAuth = renew_auth_if_expired(oAuth)"

def renew_auth_if_expired(oAuth):

    exp_datetime = datetime.datetime.strptime(oAuth["token_expires"],'%Y/%m/%d %H:%M:%S.%f')

    if exp_datetime < datetime.datetime.now():
        logging.info("Token Expired at " + oAuth["token_expires"] + ". Getting a new one.")
        oAuth = get_token(oAuth)

    else:
        logging.debug("Token will expire at " + oAuth["token_expires"])
        oAuth = oAuth

    return oAuth


#########################
# check if course is parent and get stuff about it
# returns a dictionary object for the parent course
def get_parent(courseId, oAuth):

    endpoint="/learn/api/public/v3/courses/"
    courseKey="courseId:" + courseId
    params="?fields=id,courseId,externalId,name,hasChildren"

    path = endpoint + courseKey + params
    
    oAuth = renew_auth_if_expired(oAuth)
    getParent = requests.get(HOST + path, headers={'Authorization':oAuth["authStr"]})
    if getParent.status_code != 200:
        print ('Error getting course: ' + courseId)
        print ('Status: ' + str(getParent.status_code))
        sys.exit()
    parent = json.loads(getParent.text)
    logging.debug("Parent:  " + getParent.text)
    if parent["hasChildren"]:
        logging.info(courseId + " is a Parent Course... continuing")
    else:
        logging.warning(courseId + " has no Children... exiting")
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
    
    oAuth = renew_auth_if_expired(oAuth)
    getChildren = requests.get(HOST + path, headers={'Authorization':oAuth["authStr"]})

    if getChildren.status_code != 200:
        logging.critical("Error Status: " + str(getChildren.status_code) + "...exiting")
        sys.exit()

    logging.debug(getChildren.text)
    response = json.loads(getChildren.text)
    check_for_paging(response)
    results = response["results"]

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

    logging.info(courseId + " has " + str(len(children)) + " merged children.")



    return children


#########################
# build the courseList
# returns a list of dictionaries with list element for parent and each child course
def build_course_list(parent, children):
    courseList = []
    courseList.append(parent.copy())
    courseList.extend(children)
    logging.debug(courseList)
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
    
    path = endpoint + courseKey + params + setKey

    oAuth = renew_auth_if_expired(oAuth)
    getSet = requests.get(HOST + path, headers={'Authorization':oAuth["authStr"]})

    if getSet.status_code == 200:     #it exists, get the id        
        set = json.loads(getSet.text)
        groupSetId = set["id"]
        logging.info("The group set exists for course: " + parent["courseId"] + ". The set id is " + groupSetId)
        return groupSetId

    elif getSet.status_code == 404:  #doesn't exist, create it      
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
        logging.debug("PAYLOAD: " + str(body))
        path = endpoint + courseKey + params

        createSet = requests.post(HOST + path, headers={'Authorization':oAuth["authStr"]},json = body)

        if createSet.status_code != 201:
            logging.critial('Error creating group set in course: ' + parent['courseId'] + 'Status: ' + str(createSet.status_code))
            sys.exit()
        set = json.loads(createSet.text)
        groupSetId = set["id"]
        logging.info("Created the group set for course:  " + parent["courseId"] + ". The set id is " + groupSetId)
        return groupSetId
    
    else:
        logging.critical(str(getSet.status_code) + " Error syncing the group set in : " + parent["courseId"] + "...exiting.")
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

    oAuth = renew_auth_if_expired(oAuth)
    getGroups = requests.get(HOST + path , headers={'Authorization':oAuth["authStr"]})
    if getGroups.status_code != 200:
        logging.critical('Error getting groups for course: ' + myCourse + "...exiting.")
        sys.exit()
    logging.debug("Response: " + getGroups.text) 
    response = json.loads(getGroups.text)
    check_for_paging(response)
    groups = response["results"]

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
    logging.debug("PAYLOAD :" + str(body))
    
    oAuth = renew_auth_if_expired(oAuth)
    createGroup = requests.post(HOST + path, headers={'Authorization':oAuth["authStr"]},json = body)
    if createGroup.status_code !=201:
        logging.critical("Status: " + str(createGroup.status_code) + "...exiting.")
        sys.exit()
    logging.debug(createGroup.text)
    thisGroup = json.loads(createGroup.text)   
    logging.info("Created group " + thisGroup["name"] + ". The group id is " + thisGroup["id"])


#########
# delete a group in the course
def delete_group(g,courseId,oAuth):

    endpoint= "/learn/api/public/v2/courses/"
    courseKey= "courseId:" + courseId
    params= "/groups/"
    groupKey= g["id"]

    path = endpoint + courseKey + params + groupKey

    oAuth = renew_auth_if_expired(oAuth)
    deleteGroup = requests.delete(HOST + path, headers={'Authorization':oAuth["authStr"]})
    print(deleteGroup)
    if deleteGroup.status_code !=204:
        logging.critical('Error Status: ' + str(deleteGroup.status_code) + "...exiting.")
        sys.exit()
    logging.info("Deleted the group " + g["externalId"])



#######################
# return a courseRoster list of dictionaries from parent course

def get_course_roster (parent, courseList, oAuth):
    courseId = parent["courseId"]
    
    endpoint="/learn/api/public/v1/courses/"
    courseKey="courseId:" + courseId
    params="/users?expand=user&fields=id,userId,courseRoleId,childCourseId,user.userName,availability.available"

    path = endpoint + courseKey + params
    
    oAuth = renew_auth_if_expired(oAuth)
    getEnrollments = requests.get(HOST + path, headers={'Authorization':oAuth["authStr"]})
    if getEnrollments.status_code != 200:
        logging.critical('Error Status: ' + str(getEnrollments.status_code) + "...exiting.")
        sys.exit()
    logging.debug("Response: " + getEnrollments.text)
    response = json.loads(getEnrollments.text)
    check_for_paging(response)
    
    enrollments = response["results"]
    logging.info("Number of enrollments: "+ str(len(enrollments)))

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

        oAuth = renew_auth_if_expired(oAuth)
        getGroupMems = requests.get(HOST + path, headers={'Authorization':oAuth["authStr"]})
        if getGroupMems.status_code != 200:
            logging.critical('Error Status: ' + str(getGroupMems.status_code) + "...exiting.")
            sys.exit()
    
        logging.debug("Response: " + getGroupMems.text)
        response = json.loads(getGroupMems.text)
        check_for_paging(response)
        members = response["results"]
        for m in members:
            m["externalGroupId"] = g["externalId"]
            m["groupId"] = g["id"]
        
        groupRoster.extend(members)

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

    logging.debug("The Action Plan: " + str(actionPlan))

    ### execute the plan

    for a in actionPlan:
        if a["action"] == "add":
            logging.info("Adding user " + a["userName"] + " to group " + a["externalCourseId"])
            group_mem_action(oAuth,courseId,a["userName"],a["externalCourseId"],"add")
        elif a["action"] == "move":
            logging.info("Moving user " + a["userName"] +" from group " + a["delGroup"] + " to group " + a["externalCourseId"])
            group_mem_action(oAuth,courseId,a["userName"],a["delGroup"],"remove")
            group_mem_action(oAuth,courseId,a["userName"],a["externalCourseId"],"add")
        else:
            logging.info("Doing nothing with " + a["userName"])


#################################
## add and remove group members
def group_mem_action(oAuth,courseId,userName,externalGroupId,action):

    endpoint= "/learn/api/public/v2/courses/"
    courseKey= "courseId:" + courseId
    params= "/groups/"
    groupKey= "externalId:" + externalGroupId
    params2= "/users/"
    userKey= "userName:" + userName

    path = endpoint + courseKey + params + groupKey + params2 + userKey

    if action == "add":
        oAuth = renew_auth_if_expired(oAuth)
        userAction = requests.put(HOST + path, headers={'Authorization':oAuth["authStr"]})
    elif action == "remove":
        oAuth = renew_auth_if_expired(oAuth)
        userAction = requests.delete(HOST + path, headers={'Authorization':oAuth["authStr"]})


    if userAction.status_code == 201:
        logging.debug("User added")
    elif userAction.status_code == 204:
        logging.debug("User removed")
    else:
        logging.critical("Error Status: " + str(userAction.status_code) + "...exiting.")
        sys.exit()


#############
##run it!!

main()
logging.info("Finished with Course " + COURSEID)


