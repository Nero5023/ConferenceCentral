# Conference Central
## Purpose:
----------
Develop an app with EndPoints using Google's App Engine. All the work is focused on the back end API.
## Description:
----------
Develop a cloud-based API server to support a provided conference organization application that exists on the web as well as a native Android application. The API supports the following functionality found within the app: user authentication, user profiles, conference information and various manners in which to query the data.


## App architected design
----------
####Speaker
**Speaker** is the person who speaks in the session. **Speaker** store the speaker's info: name, email, company, sex, field. Speaker should be created before Session

| Property | Data Type & Desctiption |
| -------- | ----------------------- |
|name|**StringProperty(required=True)** Beasuce name is a string, of course it's a string, and  it's requireed|
|email|**StringProperty(required=True)** This field is required. Because everyone's email is unique, email can be used as ID to create key.|
|company|**StringProperty()** This field is used to store the speaker's company that he works for. It is optional.|
|sex|**StringProperty()** This field stores the speaker's gender. (Male and Female)|
|field|**StringProperty(repeated=True)** This field is a list, to store the speaker's fields that he is good at.|

#### Session
Session is belong to a conference. It's **ancestor** is **Conference**. **Session** has a **has-a** relation with **Speaker**, holding the speakerid(emial). **Session** need a **Speaker** entity and **Conference** entity.

| Property | Data Type & Desctiption |
| -------- | ----------------------- |
|name|**StringProperty(required=True)** The name of the session, and it's required.|
|highlights|**StringProperty(repeated=True)** A list of highlights of session.|
|speaker|**ndb.StringProperty()** This field the **speaker's email**, and it's required|
|duration|**FloatProperty()** The number of hours of session will last. |
|typeOfSession|**StringProperty(default='NOT_SPECIFIED')** This field uses enum values for typeOfSession to limit choices of type.|
|date|**DateProperty()** The date of the session hold.|
|startTime|**TimeProperty()** The time of the session starts.|

#### Relationship
**Conference** is **Session**'s ancestor.  
**Session** has-a **Speaker**

## Tasks
---------------
#### Taks1
Session is a part of a conference, so I create the session as a child of the conference. Because every session has a speaker, I store the speaker's id(email) in the session. The APIs with Speaker are **querySpeakers** and **createSpeaker**.     

* **querySpeakers** Use a list of SpeakerForm to query for speakers, a little like the querys for Conference
* **createSpeaker** Use SpeakerForm to create a speaker.  

Becase speaker's emial is unique, I use it as id for **Speaker**, like userid for **Profile**.
#### Task2
I add a property: **wishlist = ndb.StringProperty(repeated=True)** to the **Profile** to store the sessions that they are interested in.
#### Task3
######  Additional queries

* **getSessionsWithHighlights**: Users can search for a list of sessions in which each session matches one or more highlights from a list of highlights that they type in. This query allows the user to put in a list of highlights in which they're interested and return the results that match one or more of the highlights in the list.
* **querySpeakers** User can search for speakers in which each speaker meet in input requirement, such as name, the company they work for, the fileds they good at, ect. This query makes user able to acces the speakers they want to find by their input information and will return the results that match all the input fiield. 

* **getSessionsWithSpeakerField** User can searching for a list of sessions in which session speaker's fields value contains at leat one of those input fields. Image that people want attend the sessions that are in specific field for example Python, Ruby, Swift, etc . It's likely that some spakers who are the experts in these field will do these sessions, so using this query may be a good choice.

###### Query problem

###### Reason for the problem with this query
This query will uses a inequality filter for two different properties, one for Session.typeOfSession != Workshop and another for Session.startTime < 7p.m., it is a query restrictions on DataStore. Reference:[Udacity Course](https://www.udacity.com/course/viewer#!/c-ud858-nd/l-3839678726/m-1497718606)
###### Solutions
First, I fetch all the sessions that before 7 pm, then in the for loop check the session if is    non-workshop if it is then append in a array, finally return the results.

Detailed implementation is in the `conference.py` `taks3` method.


#### Task4
Staticmethod method **_cacheFeaturedSpeaker** called with url **/tasks/set_featured_speaker**.
See details in the file **main.py**

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
------------------
#### Installation Steps:
1. Open terminal:
  - Windows: Use the Git Bash program (installed with Git) to get a Unix-style
  terminal.
  - Other systems: Use your favorite terminal program.
2. Change to the desired parent directory
  - Example: `cd Desktop/`
3. Using Git, clone this project:
  - Run: `git clone https://github.com/Nero5023/ConferenceCentral.git
  Conference_Central`
  - This will create a directory inside of your parent directory titled
  *Conference_Central*.
4. Download the Google App Engine SDK *for Python* using the link listed under
**Prerequisites**.
5. Once the SDK is installed, open GoogleAppEngineLauncher.
6. Under File, select *Add Existing Application...*.
7. Select *Browse* and navigate to the newly created Conference_Central Folder.
8. (Optional) Adjust the *Admin Port* and *Port* if desired and make note of
both.
9. With the newly added application highlighted, press *Run*.
10. The APIs explorer should now be available at
http://localhost:8080/_ah/api/explorer
  - The url above assumes the default port.  If *Port* was altered in step 8,
  replace *8080* with the new port provided.
11. Select *conference API* to access all EndPoints.


# Happy New Year!

[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool
