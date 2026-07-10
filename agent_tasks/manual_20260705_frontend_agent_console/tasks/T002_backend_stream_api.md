# T002

Add backend session APIs for the web chat panel.

Required endpoints:
- create session
- stream session events
- read session state
- cancel session

The stream event type must be answer_delta for visible answer text.
System events and diagnostic lines must use separate event types.
