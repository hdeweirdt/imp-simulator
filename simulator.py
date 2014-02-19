#!/usr/bin/python3
import sys
import sqlite3 as lite
import json
import logging
import os
from random import shuffle

from Imp import app
from Imp import resources

#if len(sys.argv) != 2:
#    sys.exit('Incorrect number of arguments given.\nOnly a file containing the json data can be given.\n')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
loghandler = logging.FileHandler('/tmp/simlog')
logger.addHandler(loghandler)

with open('test.json', 'r') as data_file:    
    parsed_json = json.loads(data_file.read())

filesystem = [line.strip() for line in open('filesystem')]

deployment_db = lite.connect('deployment.db')
pkgdatata_db = lite.connect('pkgfiles.sqlite')

"""
Initialise the database structure
"""
def init_database():
    with deployment_db:
        depl_cur = deployment_db.cursor()
        #Create the tables
        depl_cur.execute("CREATE TABLE IF NOT EXISTS Agent(Name TEXT, UNIQUE(Name));")
        #Unique so that we don't enter the same ID twice
        depl_cur.execute("CREATE TABLE IF NOT EXISTS Resource(Id TEXT, UNIQUE(Id));")
        depl_cur.execute("CREATE TABLE IF NOT EXISTS Attribute(name TEXT, value TEXT, ResourceId TEXT, UNIQUE(name,value,ResourceId));")
        depl_cur.execute("CREATE TABLE IF NOT EXISTS Relation(name TEXT, side1ID TEXT, side2ID TEXT);")
        deployment_db.commit()

init_database()

def valid_deployment(resource):
    res_type = resources.Id.parse_id(resource['id']).get_entity_type()
    logger.info("Resource: %s\nRes type: %s" % (resource,res_type))

    with deployment_db:
        depl_cur = deployment_db.cursor()
        depl_cur.execute("SELECT * FROM Resource")
        #Alternative: select * from Attribute where name like 'path'
        rows = depl_cur.fetchall()
        directories = [resources.Id.parse_id(row[0]).get_attribute_value() for row in rows]

    if res_type == "std::File":
        logger.info("Checking for valid File deployment")
        logger.info("File path: %s " % resource['path'])
        parent_folder = os.path.dirname(resource['path'])
        logger.info("Directories: %s" % directories)
        if not (parent_folder in filesystem or parent_folder in directories):
            logger.error("Parent folder doesn't exist! File not deployed")

    elif res_type == "std::Service":
        logger.info("Checking for valid Service deployment")
        srv_name = resources.Id.parse_id(resource['id']).get_attribute_value()
        with pkgdatata_db:
            pkg_cur = pkgdatata_db.cursor()
            pkg_cur.execute("SELECT * FROM pkgdata WHERE name LIKE ?", srv_name)
            srv_files = pkg_cur.fetchall()


    elif res_type == "std::Package":
        logger.info("Checking for valid Package deployment")

    elif res_type == "std::Directory":
        logger.info("Checking for valid Directory deployment")
        parent_folder = os.path.dirname(resource['path'])
        logger.info("Directories: %s" % directories)
        if not (parent_folder in filesystem or parent_folder in directories):
            logger.error("Parent folder doesn't exist! Directory not deployed")

    return True

#Converts two strings like "/usr/bin" and "test/test2" into a list containing "/usr/bin/test" and /usr/bin/test2"
def filenames_to_files(prefix, filenames):
    return [prefix + '/' + suffix for suffix in filenames.split('/')]

"""
Write a resource to the database
Returns the written resource
Checks doe hier.
"""
def write_to_database(resource):
    res_type = resources.Id.parse_id(resource['id']).get_entity_type()
    res_name = resources.Id.parse_id(resource['id']).get_attribute_value()

    with deployment_db:
        depl_cur = deployment_db.cursor()
        #First check if there would be no errors during the deployment of this resource
        if valid_deployment(resource):
            for attr, val in resource.items():
                if attr == 'id' :
                    depl_cur.execute("INSERT OR IGNORE INTO Resource VALUES(?)", (val,))
                else:
                    depl_cur.execute("INSERT OR IGNORE INTO Attribute VALUES(?, ?, ?)", (attr, str(val), resource['id']))
            logger.info("Resource with id %s  written" % resource['id'])

            #Deploy additional resources found in pkginfo
            if res_type == "std::Package":
                with pkgdatata_db:
                    pkg_cur = pkgdatata_db.cursor()
                    pkg_cur.execute("SELECT * FROM pkgdata WHERE name LIKE (?)", (res_name,))
                    pkg_files = []
                    rows = pkg_cur.fetchall()
                    pkg_files = []
                    for row in rows:
                        pkg_files.append(filenames_to_files(row[2], row[3]))
                    #flatten
                    pkg_files = [item for sublist in pkg_files for item in sublist]

                    #The id was already written, now write extra path Attributes
                    for file in pkg_files:
                        depl_cur.execute("INSERT OR IGNORE INTO Attribute VALUES(?, ?, ?)", ("path", file, resource['id']))


        else:
            logger.error("Tried to deploy resource but failed")

    return resource


"""
Look for the different agents and write them in the database
"""
agent_list = set()
for res in range(0, len(parsed_json)):
    id = parsed_json[res]['id']
    parsed_id = resources.Id.parse_id(id)
    agent_name = parsed_id.get_agent_name()
    agent_list.add(agent_name)

    #write into db
    deployment_db = lite.connect('deployment.db')
    with deployment_db:
        cur = deployment_db.cursor()
        #Ignore so that we continue if the same Id is entered again
        cur.execute("INSERT OR IGNORE INTO Agent VALUES(?)", (agent_name,))

"""
Group resources per agent
"""
agent_to_res = dict()
for agent in agent_list:
    agent_to_res[agent] = []

for res in range(0, len(parsed_json)):
    id = parsed_json[res]['id'] 
    res_agent = resources.Id.parse_id(id).get_agent_name()
    agent_to_res[res_agent].append(parsed_json[res])

def finished_deploying(agent_res_dict):
    for agent in agent_res_dict.keys():
        logger.info("Checking if agent %s has resources left to deploy." % agent)
        if any(agent_res_dict[agent] for agent in agent_to_res.keys()):
            logger.info("Resources left for agent %s: %s " % (agent, agent_to_res[agent]))
            return False

    return True

"""
The simulation itself
"""
#as long as not everything has been deployed
while not finished_deploying(agent_to_res):
    #deploy the resources without requirements in every agent
    for agent in agent_list:
        logger.info("Deploying resources for agent %s." % agent)
        res_list = agent_to_res[agent]
        #by getting the list of resources without requirements, and deploying them
        no_reqs = [write_to_database(res) for res in res_list if not res['requires']]
        for agent in agent_list:
            #and getting those resources who do have requirements.
            reqs = [x for x in agent_to_res[agent] if x not in no_reqs]
            logger.info("Resources without requirements: %s \n Resources with requirements: %s" % (len(no_reqs), len(reqs)))
            #Then remove the written resources from the requirements of the remaining resources
            for res in reqs:
                for possible_req in no_reqs:
                    logger.info("Checking if %s can be removed from the requirements of %s." % (possible_req['id'], res['id']))
                    if possible_req['id'] in res['requires']:
                        logger.info("Removed %s from the requirements of %s." % (possible_req, res))
                        res['requires'].remove(possible_req['id'])

            #In the end we remove the newly deployed resources from the resource list of the agent.
            agent_to_res[agent] = reqs




##select ResourceId, name, value FROM Attribute, Resource where Attribute.ResourceId = Resource.Id order by ResourceId asc;
