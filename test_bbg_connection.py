"""
Run this directly to diagnose Bloomberg connectivity:
    python test_bbg_connection.py
"""
import sys
sys.path.insert(0, r"C:\claude\GDP_System1")

print("Step 1: Importing blpapi...")
try:
    import blpapi
    print("  OK - blpapi imported")
except ImportError as e:
    print(f"  FAIL - blpapi not installed: {e}")
    sys.exit(1)

print("Step 2: Creating session...")
options = blpapi.SessionOptions()
options.setServerHost("localhost")
options.setServerPort(8194)
session = blpapi.Session(options)

print("Step 3: session.start()...")
started = session.start()
print(f"  Result: {started}")

if not started:
    print("  FAIL - Bloomberg Terminal not reachable at localhost:8194")
    print("  Is the Bloomberg Terminal application open and logged in?")
    sys.exit(1)

print("Step 4: openService(//blp/refdata)...")
opened = session.openService("//blp/refdata")
print(f"  Result: {opened}")

print("Step 5: Quick BDH test (GDP CUR$ Index)...")
refDataService = session.getService("//blp/refdata")
request = refDataService.createRequest("HistoricalDataRequest")
request.getElement("securities").appendValue("GDP CUR$ Index")
request.getElement("fields").appendValue("PX_LAST")
request.set("startDate", "20240101")
request.set("periodicitySelection", "QUARTERLY")
session.sendRequest(request)

rows = []
while True:
    ev = session.nextEvent(500)
    for msg in ev:
        if msg.hasElement("securityData"):
            sec_data = msg.getElement("securityData")
            field_data = sec_data.getElement("fieldData")
            for i in range(field_data.numValues()):
                fv = field_data.getValue(i)
                rows.append((fv.getElementAsDatetime("date"), fv.getElementAsFloat("PX_LAST")))
    if ev.eventType() == blpapi.Event.RESPONSE:
        break

print(f"  Got {len(rows)} rows")
for date, val in rows[-3:]:
    print(f"    {date} -> {val}")

session.stop()
print("\nAll steps passed - Bloomberg is working.")
