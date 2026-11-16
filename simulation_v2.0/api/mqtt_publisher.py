import asyncio
from json import dumps
from logging import getLogger
from threading import Event, Thread

from amqtt.broker import Broker
from paho.mqtt import client as paho_mqtt_client

from api import api_settings


# ================================================ 이벤트 데이터의 토픽 이름: 토픽 앞머리(기본 /이벤트-데이터) 뒤에 붙음 ================================================
EVENT_TOPIC_NAMES = {
    'machine': '설비',
    'worker_process': '작업자-공정',
    'warehouse': '창고-입출고',
    'defect': '불량',
    'box_completion': '박스-완료',
}


# ================================================ MQTT 접속 값: 내장 브로커에 접속할 주소, 내장 브로커가 켜지기를 기다리는 시간(실시간 초), 접속 유지 확인 간격(실시간 초) ================================================
EMBEDDED_BROKER_HOST = '127.0.0.1'
EMBEDDED_BROKER_START_WAIT_SEC = 5.0
MQTT_KEEPALIVE_SEC = 30


LOGGER = getLogger('cpro.publisher')


# ================================================ 내장 브로커 켜기: 외부 브로커 주소가 설정에 없을 때 서버가 별도 스레드에서 브로커를 띄움 ================================================
def start_embedded_broker():
    if not api_settings.MQTT_ENABLED:
        return
    if api_settings.MQTT_EXTERNAL_BROKER_ADDRESS != api_settings.NO_EXTERNAL_MQTT_BROKER:
        return
    bind_address = f'{api_settings.MQTT_EMBEDDED_BROKER_BIND_HOST}:{api_settings.MQTT_PORT}'
    broker_started_or_failed = Event()
    broker_thread = Thread(
        target=run_embedded_broker, args=[bind_address, broker_started_or_failed],
        name='mqtt-broker', daemon=True)
    broker_thread.start()
    broker_started_or_failed.wait(timeout=EMBEDDED_BROKER_START_WAIT_SEC)
    LOGGER.info('내장 MQTT 브로커 %s', bind_address)


def run_embedded_broker(bind_address, broker_started_or_failed):
    broker_event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(broker_event_loop)
    try:
        broker_event_loop.run_until_complete(start_broker_in_event_loop(bind_address))
        broker_started_or_failed.set()
        broker_event_loop.run_forever()
    except Exception as error:
        LOGGER.warning('내장 브로커 기동 실패 (%s)', error)
        broker_started_or_failed.set()


async def start_broker_in_event_loop(bind_address):
    broker = Broker({
        'listeners': {'default': {'type': 'tcp', 'bind': bind_address}},
        'sys_interval': 0,
        'auth': {'allow-anonymous': True},
    })
    await broker.start()
    return broker


# ================================================ 발행할 브로커의 주소: 외부 브로커 주소(host:port)가 설정에 있으면 그곳, 없으면 내장 브로커 ================================================
def broker_host_and_port():
    external_broker_address = api_settings.MQTT_EXTERNAL_BROKER_ADDRESS
    if external_broker_address == api_settings.NO_EXTERNAL_MQTT_BROKER:
        return {'host': EMBEDDED_BROKER_HOST, 'port': api_settings.MQTT_PORT}
    host, separator, port_text = external_broker_address.partition(':')
    if port_text:
        port = int(port_text)
    else:
        port = api_settings.MQTT_PORT
    return {'host': host, 'port': port}


# ================================================ 이벤트 발행: 실행 작업마다 하나씩 만들어 그 구간에 생긴 이벤트를 토픽으로 내보냄. 이벤트가 없는 구간은 보내지 않음 ================================================
class EventPublisher:

    def __init__(self, job_id):
        self.client = None
        if not api_settings.MQTT_ENABLED:
            return
        broker = broker_host_and_port()
        try:
            client = paho_mqtt_client.Client(
                paho_mqtt_client.CallbackAPIVersion.VERSION2,
                client_id=f'cpro-{job_id}', clean_session=True)
            client.connect(broker['host'], broker['port'], keepalive=MQTT_KEEPALIVE_SEC)
            client.loop_start()
            self.client = client
        except Exception as error:
            LOGGER.warning('MQTT 접속 실패 (%s) — 이벤트 발행을 건너뛴다', error)

    def publish(self, topic_name, period, events):
        if self.client is None:
            return
        if not events:
            return
        topic = f'{api_settings.MQTT_TOPIC_PREFIX}/{topic_name}'
        payload = {'구간(s)': period, '이벤트': events}
        try:
            self.client.publish(
                topic, dumps(payload, ensure_ascii=False), qos=api_settings.MQTT_QOS)
        except Exception as error:
            LOGGER.warning('MQTT 발행 실패 (%s)', error)
