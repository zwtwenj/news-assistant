"""RSS 分发 schemas。"""

from pydantic import BaseModel, Field


class RssConfigIn(BaseModel):
    channel_title: str = Field(min_length=1, max_length=200)
    channel_description: str = Field(min_length=1, max_length=2000)


class RssFeedOut(BaseModel):
    feed_url: str
    channel_title: str
    channel_description: str
    published_count: int = 0
