from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(
        r'ws/pipeline/(?P<repo_id>[0-9a-f-]+)/$',
        consumers.PipelineProgressConsumer.as_asgi(),
    ),
]
