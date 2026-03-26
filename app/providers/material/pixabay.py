from typing import List
from urllib.parse import urlencode

import requests
from loguru import logger

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect
from app.providers import register_material
from app.providers.base import MaterialProvider


def _get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\n"
            f"Please set it in the config.toml file: {config.config_file}\n\n"
        )
    if isinstance(api_keys, str):
        return api_keys
    if not hasattr(_get_api_key, "_count"):
        _get_api_key._count = 0
    _get_api_key._count += 1
    return api_keys[_get_api_key._count % len(api_keys)]


@register_material
class PixabayProvider(MaterialProvider):
    @staticmethod
    def provider_name() -> str:
        return "pixabay"

    def search_videos(
        self,
        search_term: str,
        minimum_duration: int,
        video_aspect: VideoAspect = VideoAspect.portrait,
    ) -> List[MaterialInfo]:
        aspect = VideoAspect(video_aspect)
        video_width, video_height = aspect.to_resolution()

        api_key = _get_api_key("pixabay_api_keys")
        params = {
            "q": search_term,
            "video_type": "all",
            "per_page": 50,
            "key": api_key,
        }
        query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
        logger.info(f"searching videos: query={search_term}, source=pixabay")

        try:
            r = requests.get(query_url, proxies=config.proxy, timeout=(30, 60))
            response = r.json()
            video_items = []
            if "hits" not in response:
                logger.error(f"search videos failed: {response}")
                return video_items
            videos = response["hits"]
            for v in videos:
                duration = v["duration"]
                if duration < minimum_duration:
                    continue
                video_files = v["videos"]
                for video_type in video_files:
                    video = video_files[video_type]
                    w = int(video["width"])
                    if w >= video_width:
                        item = MaterialInfo()
                        item.provider = "pixabay"
                        item.url = video["url"]
                        item.duration = duration
                        video_items.append(item)
                        break
            return video_items
        except Exception as e:
            logger.error(f"search videos failed: {str(e)}")

        return []
