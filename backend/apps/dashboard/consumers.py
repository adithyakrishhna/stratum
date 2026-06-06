from channels.generic.websocket import AsyncJsonWebsocketConsumer


class PipelineProgressConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for live pipeline progress updates (Dashboard Page 7).
    Clients join a group keyed by repo_id to receive real-time stage updates.
    """

    async def connect(self):
        self.repo_id = self.scope['url_route']['kwargs']['repo_id']
        self.group_name = f'pipeline_{self.repo_id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def pipeline_update(self, event):
        await self.send_json(event['data'])
