"""Amazon PA API ユーティリティ。

キーワードで Amazon Japan を検索し、レビュー数・評価が高い商品を1件返す。
PA_API_ACCESS_KEY / PA_API_SECRET_KEY が未設定の場合は None を返す。
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AmazonProduct:
    asin: str
    title: str
    url: str          # アソシエイトタグ付き商品ページURL
    price_jpy: int | None
    rating: float | None
    review_count: int | None


def search_best_product(
    keyword: str,
    access_key: str,
    secret_key: str,
    associate_tag: str,
    min_reviews: int = 10,
) -> AmazonProduct | None:
    """キーワードで Amazon Japan を検索し、最もレビューが多い商品を返す。

    Args:
        keyword: 検索キーワード（例: "電動工具 充電式"）
        access_key: PA API アクセスキー
        secret_key: PA API シークレットキー
        associate_tag: アソシエイトタグ（例: "tennki7770f-22"）
        min_reviews: 最低レビュー件数フィルター

    Returns:
        AmazonProduct または None（APIキー未設定・エラー時）
    """
    if not access_key or not secret_key:
        logger.info("PA API キー未設定。商品検索をスキップ。")
        return None

    try:
        from amazon_creatorsapi import AmazonCreatorsApi, Country
        from amazon_creatorsapi.models import SearchItemsResource, SortBy

        api = AmazonCreatorsApi(
            credential_id=access_key,
            credential_secret=secret_key,
            version="5",
            tag=associate_tag,
            country=Country.JP,
        )

        resources = [
            SearchItemsResource.ITEMINFO_TITLE,
            SearchItemsResource.OFFERS_LISTINGS_PRICE,
            SearchItemsResource.CUSTOMERREVIEWS_COUNT,
            SearchItemsResource.CUSTOMERREVIEWS_STARRATING,
        ]

        result = api.search_items(
            keywords=keyword,
            search_index="All",
            item_count=5,
            sort_by=SortBy.RELEVANCE,
            resources=resources,
        )

        if not result or not result.search_result or not result.search_result.items:
            logger.info("[PA API] '%s' の検索結果なし", keyword)
            return None

        # レビュー数が多い順に並べて最上位を選ぶ
        best = None
        best_reviews = -1

        for item in result.search_result.items:
            reviews = 0
            rating = None
            price = None

            if item.customer_reviews:
                reviews = item.customer_reviews.count or 0
                rating = item.customer_reviews.star_rating

            if reviews < min_reviews:
                continue

            if item.offers and item.offers.listings:
                listing = item.offers.listings[0]
                if listing.price and listing.price.amount:
                    price = int(listing.price.amount)

            if reviews > best_reviews:
                best_reviews = reviews
                title = (
                    item.item_info.title.display_value
                    if item.item_info and item.item_info.title
                    else keyword
                )
                url = item.detail_page_url or (
                    f"https://www.amazon.co.jp/dp/{item.asin}?tag={associate_tag}"
                )
                best = AmazonProduct(
                    asin=item.asin,
                    title=title,
                    url=url,
                    price_jpy=price,
                    rating=rating,
                    review_count=reviews,
                )

        if best:
            logger.info(
                "[PA API] '%s' → %s（レビュー%d件, ★%.1f）",
                keyword, best.title[:30], best.review_count or 0, best.rating or 0,
            )
        else:
            logger.info("[PA API] '%s' はレビュー%d件以上の商品なし", keyword, min_reviews)

        return best

    except Exception as e:
        logger.warning("[PA API] 検索失敗 keyword='%s': %s", keyword, e)
        return None
