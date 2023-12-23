import os
import sys
import requests
import json
import subprocess

##########################################
# A function to find all occurrences of a substring in a string.
def find_all(a_str, sub):
  start = 0
  while True:
    start = a_str.find(sub, start)
    if start == -1: return
    yield start
    start += len(sub)
##########################################
    
print()
print()

hubs_domain = "metabi-poc-hub.com"
old_domain = "shared-hubs-assets.metabi-vr-hubs.com"
ret_pod = "moz-reticulum-55d7b64f49-ss424"
pgsql_pod = "moz-pgsql-587fb8ccb8-8rtkj"

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

csv_file = sys.argv[1]

#Since the same script is going to deal with json as well as asset files, in case we are handling json we want to load this now.
uuids= {}
try:
  uuid_map = open('uuid_map.txt',mode='r')
  for line in uuid_map:
    old_id,new_id = line.strip().split(",")
    uuids[old_id] = new_id
  uuid_map.close()
except:
  print("No uuid_map.txt file found. This is OK if we are not importing json.")

#But if it is assets we are dealing with, all we are going to do is append to the uuid_map file.
uuid_map = open('uuid_map.txt',mode='a')
sql_file = open('update.sql',mode='w')
unsql_file = open('unupdate.sql',mode='w')
cp_dirs_file = open('cp_dirs.sh',mode='w')

# I made a file called token.txt holding my JWT token from the hubs client browser storage.
with open('token.txt',mode='r') as token_file:
  token = token_file.read()
token = token.strip('\n')

api_endpoint = f"https://{hubs_domain}/api/v1/media"
auth_header = { 
  "Authorization" : "bearer " + token
}

dirs = []
ext = ""
base_url = f"https://{old_domain}/files/"
with open(csv_file, "r") as filestream:
  for line in filestream:
    #print(line)
    file_id, uuid, key, account_id, type = line.strip().split(",")
    if file_id == 'owned_file_id': # get rid of headers line
      continue

    if type == 'application/json':
      ext = ".json"
    elif type == 'model/gltf-binary':
      ext = ".glb"
    elif type == "model/gltf":
      ext = ".glb"
    elif type == "image/png":
      ext = ".png"
    elif type == "image/jpeg":
      ext = ".jpg"
    elif type == "application/octet-stream":
      ext = ""

    url = base_url + uuid + ext
    destination = "files/" + uuid + ext
    try:
      if not os.path.exists(destination):
        print("downloading " + url)
        filedata = requests.get(url)
        if ext == ".json": 
          #modified_json_string = re.sub(re.escape(old_string), new_string, json_content)
          #WARNING, CHECK THIS, I had b"metabi-poc-hub.com" before, but I need f"..." to use a variable instead
          # but now I probably have a byte vs text issue here that will need either .encode or .decode
          new_content = filedata.content.replace(f"{old_domain}",f"{hubs_domain}").decode('utf-8') #???
          doms_list = list(find_all(new_content,hubs_domain))
          # From the starting letter of metabi-poc-hub to the start of the uuid is 25 characters
          # then the uuid is 36 characters long
          for d in doms_list:
            prev_uuid = new_content[d+25:d+25+36]
            if prev_uuid in uuids:
              post_uuid = uuids[prev_uuid]
              new_content = new_content.replace(prev_uuid,post_uuid)
            else:
              print("could not find in uuids: " + prev_uuid)
          with open(destination, 'wb') as file:
            file.write(new_content.encode('utf-8'))
        else:
          with open(destination, 'wb') as file:
            file.write(filedata.content)
      else:
        print("file exists " + destination)
      shortname = uuid + ext
      formData = {"media": (shortname, open(destination,mode='rb'),type)}
      response = requests.post(
        url=api_endpoint,
        headers=auth_header,
        verify=False,
        files=formData
      )
      response_json = response.json()
      new_uuid = response_json["file_id"]
      key = response_json["meta"]["access_token"]
      full_url = response_json["origin"]
      top_dir = new_uuid[:2]
      if top_dir not in dirs:
        dirs.append(top_dir)

      if ext != ".json": 
        uuid_map.write(f"{uuid},{new_uuid}\n")

      query = f"UPDATE owned_files SET owned_file_uuid='{new_uuid}', key='{key}' WHERE owned_file_uuid='{uuid}';\n"
      sql_file.write(query)
      query = f"UPDATE owned_files SET owned_file_uuid='{uuid}', key='{key}' WHERE owned_file_uuid='{new_uuid}';\n"
      unsql_file.write(query)
      subprocess.call(f"rm {destination}",shell=True)
      print("new uuid: " + response_json["file_id"])
      print()
    except Exception as ex:
      print("had a problem: " + ex.__str__())

uuid_map.close()
sql_file.close()
unsql_file.close()

for d in dirs:
  cp_dirs_file.write(f"cp -r /storage/expiring/{d} /storage/owned\n")
cp_dirs_file.close()

subprocess.call(f"kubectl cp cp_dirs.sh {ret_pod}:/cp_dirs.sh",shell=True)
subprocess.call(f"kubectl exec -it {ret_pod} -- bash /cp_dirs.sh",shell=True)
subprocess.call(f"kubectl exec -it {ret_pod} -- rm -rf /storage/expiring/*",shell=True)

subprocess.call(f"kubectl cp update.sql {pgsql_pod}:/update.sql",shell=True)
subprocess.call(f"kubectl exec -it {pgsql_pod} -- psql  -U postgres -h localhost retdb < update.sql",shell=True)
