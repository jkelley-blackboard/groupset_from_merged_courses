# groupset_from_merged_courses
Python module to automatically synchronize groups and group membership based on a merged courses and enrollments.

usage = group_sync.py courseId properties_file

Functional Logic:

- Authenticate to get token
- Get parent course info
- Get child course info
- Get parent course roster info
- Sync Groups
   - Get group set
   - Create one if it doesn't exist
   - Get groups in set
   - Delete and Create groups
- Sync Members
   - Get memberships in groups in set
   - Compare to course roster
   - Delete and Create group members based on roster


Minimum Privilege and entitlement mapping in the properties file
