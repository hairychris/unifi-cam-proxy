import subprocess
import tempfile

import aiofiles

from aiohttp import ClientSession, BasicAuth, web

from unifi.cams.base import UnifiCamBase


class RTSPCam(UnifiCamBase):
    def __init__(self, args, logger=None):
        super(RTSPCam, self).__init__(args, logger)
        self.args = args
        self.event_id = 0
        self.snapshot_dir = tempfile.mkdtemp()
        self.snapshot_stream = None
        self.runner = None

    @classmethod
    def add_parser(self, parser):
        super().add_parser(parser)
        parser.add_argument("--source", "-s", required=True, help="Stream source")
        parser.add_argument("--username", "-u", required=False, help="Camera username")
        parser.add_argument("--password", "-p", required=False, help="Camera password")
        parser.add_argument("--snapshot_url", "-i", required=False, help="Snapshot image")
        parser.add_argument(
            "--http-api",
            default=0,
            type=int,
            help="Specify a port number to enable the HTTP API (default: disabled)",
        )

    async def get_snapshot(self):
        if not self.args.snapshot_url:
            return self.get_snapshot_ffmpeg()
        else:
            return await self.get_snapshot_url()

    async def get_snapshot_ffmpeg(self):
        if not self.snapshot_stream or self.snapshot_stream.poll() is not None:
            cmd = f'ffmpeg -nostdin -y -re -rtsp_transport {self.args.rtsp_transport} -i "{self.args.source}" -vf fps=1 -update 1 {self.snapshot_dir}/screen.jpg'
            self.logger.info(f"Spawning stream for snapshots: {cmd}")
            self.snapshot_stream = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True
            )
        return "{}/screen.jpg".format(self.snapshot_dir)

    async def get_snapshot_url(self):
        img_file = "{}/screen.jpg".format(self.snapshot_dir)
        url = self.args.snapshot_url
        self.logger.info(f"Fetching snapshot... {img_file} {url}")
        try:
            async with self.session.request("GET", url) as resp:
                async with aiofiles.open(img_file, "wb") as f:
                    await f.write(await resp.read())
        except aiohttp.ClientError:
            self.logger.error("Failed to get snapshot")
        return img_file

    async def run(self):
        if self.args.snapshot_url:
            if not self.args.username and self.args.password:
                self.logger.info('No username or password provided for snapshot')
                self.session = ClientSession()
            else:
                self.session = ClientSession(auth=BasicAuth(self.args.username, self.args.password))
        if self.args.http_api:
            self.logger.info(f"Enabling HTTP API on port {self.args.http_api}")

            app = web.Application()

            async def start_motion(request):
                self.logger.debug("Starting motion")
                await self.trigger_motion_start()
                return web.Response(text="ok")

            async def stop_motion(request):
                self.logger.debug("Starting motion")
                await self.trigger_motion_stop()
                return web.Response(text="ok")

            app.add_routes([web.get("/start_motion", start_motion)])
            app.add_routes([web.get("/stop_motion", stop_motion)])

            self.runner = web.AppRunner(app)
            await self.runner.setup()
            site = web.TCPSite(self.runner, port=self.args.http_api)
            await site.start()

    async def close(self):
        await super().close()
        if self.runner:
            await self.runner.cleanup()

        if self.snapshot_stream:
            self.snapshot_stream.kill()

    def get_stream_source(self, stream_index: str):
        return self.args.source
