"""Real raw lines pulled from log.2026_07_16_09_00_00.txt via grep, one per
billing-relevant event kind (plus a non-billing line), used across the test suite
so tests exercise the actual grammar instead of hand-invented approximations.
"""

START_OF_CALL_INDIVIDUAL = (
    '[07/16/26 14:00:15] Call Activity Update - Start of Call : CALL {Universal '
    'Call # (lower comp) = 83316 ; Sequence # = 1 ; Event Sequence # = 1 ; Type = '
    'Individual Call ; State Transition Field = n/a ; Radio Type Qualifier = '
    '(Interconnect,Interconnect ring state,Astro call) ; Source Zone ID = n/a ; '
    'Source Site ID = n/a ; Local Zone ID = 1 ; Controlling Zone ID = 1 ; '
    'Pre-Determined CZ Controlled Flag = Predetermined CZ ; Active/Busy Status = '
    'Global Active ; AAID = 268485866 ; Primary Multicast IP address = n/a ; '
    'Secondary Multicast IP address = n/a ; Voice Logging Enabled = False ; Access '
    'Method Type = Unknown} BUSY {Reason for Busy = n/a ; Zone Contributor Flag = '
    'Not Busy Contributor ; Resource Bitmap = (none)} REQUESTER {Primary ID = '
    '1335(0x537) "1335" [Security Id=1] ; Affiliation Type = Talkgroup Affiliation ; '
    'Device Type = Radio ; Affiliated ID = 100(0x64) "TN-ORG-95" [Security Id=1] ; '
    'Affiliated Zone = 1 ; Affiliated Site = 68 ; Protocol Type = APCO 25/TETRA ; '
    'Allow Multiple TG Affil = False ; Additional Primary ID = n/a "" ; Primary Call '
    'Processing ID Flag = False ; eTETRA Capability Flag = False} TARGET {Secondary '
    'ID = n/a "" [Security Id=n/a] ; Affiliation Type = n/a ; Device Type = n/a ; '
    'Affiliated ID = n/a "" [Security Id=n/a] ; Affiliated Zone = n/a ; Affiliated '
    'Site = n/a ; Protocol Type = n/a ; Allow Multiple TG Affil = False ; Additional '
    'Secondary ID = n/a "" ; Secondary Call Processing ID Flag = False ; eTETRA '
    'Capability Flag = True} INTERCONNECT {Device # = 1 ; TRIC # = 30} SECURITY '
    '{Secure Key # = n/a ; Secure Key Index = 0} RF SITES {Requested RF Site Info = '
    '(68) ; Busy RF Site Info = (none) ; Incapable RF Site Info = (none) ; Active RF '
    'Sites/Channel Info List = (68.3)} CONSOLE SITES {Requested Cnsl Site Info = '
    '(none) ; Busy Cnsl Site Info = (none) ; Incapable Cnsl Site Info = (none) ; '
    'Active Cnsl Sites/Call Count Info List = (none) ; Logging Cnsl Site = (none)} '
    'USER GROUPS {Mask = (1)} MTIG {ID = 1 ; Tline # = 1 ; Slot # = 30}'
)

START_OF_CALL_GROUP = (
    '[07/16/26 14:00:52] Call Activity Update - Start of Call : CALL {Universal '
    'Call # (lower comp) = 1281833 ; Sequence # = 1 ; Event Sequence # = 1 ; Type = '
    'Group Call ; State Transition Field = n/a ; Radio Type Qualifier = (Astro '
    'call) ; Source Zone ID = 2 ; Source Site ID = 49 ; Local Zone ID = 1 ; '
    'Controlling Zone ID = 2 ; Pre-Determined CZ Controlled Flag = Predetermined '
    'CZ ; Active/Busy Status = Global Active ; AAID = 1049729 ; Primary Multicast '
    'IP address = 228.8.97.98 (3825754466) ; Secondary Multicast IP address = n/a ; '
    'Voice Logging Enabled = False ; Access Method Type = Unknown} BUSY {Reason for '
    'Busy = n/a ; Zone Contributor Flag = Not Busy Contributor ; Resource Bitmap = '
    '(none)} REQUESTER {Primary ID = 3917(0xF4D) "3917" [Security Id=1] ; '
    'Affiliation Type = n/a ; Device Type = Radio ; Affiliated ID = n/a "" '
    '[Security Id=n/a] ; Affiliated Zone = n/a ; Affiliated Site = n/a ; Protocol '
    'Type = APCO 25/TETRA ; Allow Multiple TG Affil = False ; Additional Primary ID '
    '= n/a "" ; Primary Call Processing ID Flag = False ; eTETRA Capability Flag = '
    'False} TARGET {Secondary ID = 3800015(0x39FBCF) "Y-Balyk-ORG37" [Security '
    'Id=1] ; Affiliation Type = n/a ; Device Type = n/a ; Affiliated ID = n/a "" '
    '[Security Id=n/a] ; Affiliated Zone = n/a ; Affiliated Site = n/a ; Protocol '
    'Type = APCO 25/TETRA ; Allow Multiple TG Affil = False ; Additional Secondary '
    'ID = n/a "" ; Secondary Call Processing ID Flag = False ; eTETRA Capability '
    'Flag = False} INTERCONNECT {Device # = n/a ; TRIC # = n/a} SECURITY {Secure '
    'Key # = n/a ; Secure Key Index = 0} RF SITES {Requested RF Site Info = '
    '(68,77) ; Busy RF Site Info = (none) ; Incapable RF Site Info = (none) ; '
    'Active RF Sites/Channel Info List = (68.6,77.3)} CONSOLE SITES {Requested '
    'Cnsl Site Info = (none) ; Busy Cnsl Site Info = (none) ; Incapable Cnsl Site '
    'Info = (none) ; Active Cnsl Sites/Call Count Info List = (none) ; Logging '
    'Cnsl Site = (none)} USER GROUPS {Mask = (1)} MTIG {ID = n/a ; Tline # = n/a ; '
    'Slot # = n/a}'
)

CALL_STATE_CHANGE_CONNECTED = (
    '[07/16/26 14:00:16] Call Activity Update - Call State Change : CALL {Universal '
    'Call # (lower comp) = 83316 ; Sequence # = 2 ; Event Sequence # = 2 ; Type = '
    'Individual Call ; State Transition Field = INT Ring to Active ; Radio Type '
    'Qualifier = (Interconnect,Astro call) ; Source Zone ID = 1 ; Source Site ID = '
    'n/a ; Local Zone ID = 1 ; Controlling Zone ID = 1 ; Pre-Determined CZ '
    'Controlled Flag = Predetermined CZ ; Active/Busy Status = Global Active ; '
    'AAID = 268485866 ; Primary Multicast IP address = 228.4.67.116 (3825484660) ; '
    'Secondary Multicast IP address = 228.4.67.137 (3825484681) ; Voice Logging '
    'Enabled = False ; Access Method Type = Unknown} REQUESTER {Primary ID = '
    '1335(0x537) "1335" [Security Id=1]} TARGET {Secondary ID = n/a "" [Security '
    'Id=n/a]}'
)

LOCATION_REGISTRATION = (
    '[07/16/26 14:00:42] Mobility Update - Location Registration : STATUS {Local Zone ID = 1 ;'
    ' Mobility Request Result = Accepted ; MU Generic Reason = n/a ; Current TalkGroups in Zone = 46 ; '
    'Current Subscribers in Zone = 379} UNIT {Operating Unit ID = 5451(0x154B) "NUR UMN 5451" [Security Id=1] ;'
    ' Fixed Unit WACN ID = n/a ; Fixed Unit System ID = n/a ; Fixed Unit ID = n/a ; Class of MS = (Auth enabled,'
    ' Security Class 1 MS) ; Cipher Parameters Presence = Cipher Parameters is not presented ; '
    'Additional Operating Unit ID = n/a "" ; Individual Access Method Type = Unknown ; '
    'M-Capabilities Presence Flag = False ; QAM Capabilities Presence Flag = False} '
    'GROUP {Operating Group ID = 144(0x90) "GNPS ORG2" [Security Id=1] ; Fixed Group WACN ID = -1(0xFFFFFFFF) ; '
    'Fixed Group System ID = 65535(0xFFFF) ; Fixed Group ID = n/a ; Announcement Group ID = n/a "" [Security Id=n/a] ; '
    'Replace Previous Group Affiliation Flag = True ; Access Method Type = Unknown ; '
    'eTETRA Capability Operating Group Flag = False ; eTETRA Capability Announcement Group Flag = False ; '
    'Previous Operating Group ID = n/a ""} REQUESTER {Device Type = Radio ; Protocol Type = APCO 25/TETRA ; '
    'Affiliated Group ID = 144(0x90) "GNPS ORG2" [Security Id=1] ; Registered Zone = 1 ; Registered Site = 54 ; '
    'Registered Type = Talkgroup Affiliation ; Forwarded Flag = False ; eTETRA Capability Flag = False ; '
    'Previous Registered Site = n/a} SECURITY {Authentication Type = Implicit ; Encryption Key = Clear} '
    'SITES {in Mobility Response = (54)} GROUP DETAILS {Subscribers in Operating Group = 26 ; '
    'Subscribers in Prev Operating Group = 0 ; Sites in Operating Group = (54)} SITE DETAILS {TalkGroups in Site = 3 ; '
    'Subscribers in Site = 31 ; TalkGroups in Previous Site = 0 ; Subscribers in Previous Site = 0}'
)

UNIT_REGISTRATION = (
    '[07/15/26 14:37:00] Mobility Update - Unit Registration : STATUS {Local Zone ID = 2 ;'
    ' Mobility Request Result = Accepted ; MU Generic Reason = n/a ; Current TalkGroups in Zone = 343 ; '
    'Current Subscribers in Zone = 660} UNIT {Operating Unit ID = 3741010(0x391552) "3741010" [Security Id=1] ;'
    ' Fixed Unit WACN ID = 71(0x47) ; Fixed Unit System ID = 250(0xFA) ; Fixed Unit ID = 3741010(0x391552) ; '
    'Class of MS = (Auth enabled, Security Class 2/3 MS) ; Cipher Parameters = (TM-SCK OTARGCK '
    'encryption/OTAR) ; Additional Operating Unit ID = n/a "" ; Individual Access Method Type = Unknown ; '
    'M-Capabilities Presence Flag = False ; QAM Capabilities Presence Flag = False} '
    'GROUP {Operating Group ID = n/a "" [Security Id=n/a] ; Fixed Group WACN ID = -1(0xFFFFFFFF) ; '
    'Fixed Group System ID = 65535(0xFFFF) ; Fixed Group ID = n/a ; Announcement Group ID = n/a "" [Security Id=n/a] ; '
    'Replace Previous Group Affiliation Flag = True ; Access Method Type = Unknown ; '
    'eTETRA Capability Operating Group Flag = False ; eTETRA Capability Announcement Group Flag = False ; '
    'Previous Operating Group ID = n/a ""} REQUESTER {Device Type = Radio ; Protocol Type = APCO 25/TETRA ; '
    'Affiliated Group ID = n/a "" [Security Id=n/a] ; Registered Zone = 2 ; Registered Site = 8 ; '
    'Registered Type = Regd Not Affiliated ; Forwarded Flag = False ; eTETRA Capability Flag = False ; '
    'Previous Registered Site = n/a} SECURITY {Authentication Type = Explicit ; Encryption Key = Clear} '
    'SITES {in Mobility Response = (8)} SITE DETAILS {TalkGroups in Site = 343 ; Subscribers in Site = 15 ; '
    'TalkGroups in Previous Site = 0 ; Subscribers in Previous Site = 0}'
)

INTERCONNECT_BILLING = (
    '[07/16/26 14:00:47] Interconnect Call Billing Info Packet - MBX Info Type : '
    'CALL {Universal Call # (lower comp) = 83317 ; Controlling Zone ID = 1 ; '
    'Duration in Seconds = 30 ; Subscriber ID = 5217(0x1461) "5217" [Security '
    'Id=1] ; Type = Land to Mobile} INTERCONNECT {Route # = 1} PHONE NUMBER {Phone '
    'Encoding = n/a ; Phone # = 67805418}'
)

END_OF_CALL = (
    '[07/16/26 14:00:47] End of Call - End of Call : CALL {Universal Call # (lower '
    'comp) = 83317 ; Sequence # = 2 ; Event Sequence # = 2 ; Local Zone ID = 1 ; '
    'Controlling Zone ID = 1 ; CZ Controlled Flag = CZ Controlled ; End Of Call '
    'Reason = Normal call clearing}'
)

NON_BILLING_CONTROL_CHANNEL_UPDATE = (
    '[07/16/26 14:00:14] Control Channel Update - Site Info : SITE {Site ID = 68 ; '
    'Zone ID = 1 ; Control Channel = 3}'
)

BANNER_LINE = "===================================================="
