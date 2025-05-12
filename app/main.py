from fastapi import FastAPI
from prometheus_client import make_asgi_app
from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from app.api.endpoints import items
from app.api.endpoints import users
from app.core.config import settings


tags_metadata = [
    {"name": "users", "description": "Operations with users"},
    {"name": "items", "description": "Operations with items"},
    {"name": "admin", "description": "Admin operations"},
    {"name": "auth", "description": "Authenticate operations"},
]

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.DESCRIPTION,
    version=settings.VERSION,
    openapi_tags=tags_metadata,
    docs_url="/",
)

# Настройка ресурсов для трейсов
resource = Resource(attributes={SERVICE_NAME: "fastapi-service"})

# Добавление эндпоинта /metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Настройка трейсов
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)
otlp_exporter = OTLPSpanExporter(
    endpoint="http://tempo:4317", insecure=True
)  # Для локального использования без TLS
# Добавление процессора трейсов
span_processor = BatchSpanProcessor(otlp_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

# Инструментируем FastAPI
FastAPIInstrumentor.instrument_app(app)


app.include_router(items.item_router, tags=["items"])
app.include_router(users.router)
