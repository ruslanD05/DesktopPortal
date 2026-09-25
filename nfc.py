"""PC/SC callbacks only enqueue events; the GUI owns application state."""
try:
    from smartcard.CardMonitoring import CardMonitor, CardObserver
    from smartcard.Exceptions import CardConnectionException
except ImportError:
    CardMonitor = None
    CardObserver = object

    class CardConnectionException(Exception):
        pass

GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]


class TagObserver(CardObserver):
    def __init__(self, events):
        self.events = events

    def update(self, observable, handlers):
        added, removed = handlers
        for card in removed:
            self.events.put(('removed', str(card.reader), None))
        for card in added:
            connection = None
            try:
                connection = card.createConnection()
                connection.connect()
                data, sw1, sw2 = connection.transmit(GET_UID)
                if (sw1, sw2) == (0x90, 0x00):
                    self.events.put(('added', str(card.reader), bytes(data).hex()))
            except CardConnectionException:
                pass  # The tag may have disappeared during UID acquisition.
            except Exception as error:
                self.events.put(('error', str(card.reader), str(error)))
            finally:
                if connection is not None:
                    try:
                        connection.disconnect()
                    except Exception:
                        pass


def start_monitor(events):
    if CardMonitor is None:
        raise ImportError('NFC reader support requires pyscard.')
    monitor = CardMonitor()
    observer = TagObserver(events)
    monitor.addObserver(observer)
    return monitor, observer
