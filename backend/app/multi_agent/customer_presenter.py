"""Chinese customer-facing projections of source-backed consultation results."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

PRODUCT_NAMES = {
    "Action Camera": "运动相机",
    "Air Purifier": "空气净化器",
    "Backpack": "背包",
    "Bicycle": "自行车",
    "Bluetooth Speaker": "蓝牙音箱",
    "Bookshelf": "书架",
    "Coffee Maker": "咖啡机",
    "Cycling Helmet": "骑行头盔",
    "Desk Lamp": "台灯",
    "Digital Camera": "数码相机",
    "Dumbbell Set": "哑铃套装",
    "E-Reader": "电子书阅读器",
    "Electric Kettle": "电热水壶",
    "Electric Toothbrush": "电动牙刷",
    "Espresso Machine": "意式咖啡机",
    "Fleece Jacket": "抓绒夹克",
    "Gaming Mouse": "游戏鼠标",
    "Garden Hose": "花园水管",
    "Grill": "烧烤炉",
    "Headphones": "头戴式耳机",
    "Hiking Boots": "登山靴",
    "Indoor Security Camera": "室内安防摄像头",
    "Jigsaw Puzzle": "拼图",
    "Laptop": "笔记本电脑",
    "LED Light Bulb": "LED 灯泡",
    "Luggage Set": "行李箱套装",
    "Makeup Kit": "彩妆套装",
    "Mechanical Keyboard": "机械键盘",
    "Notebook": "纸质笔记本",
    "Office Chair": "办公椅",
    "Patio Umbrella": "庭院遮阳伞",
    "Perfume": "香水",
    "Pet Bed": "宠物床",
    "Portable Charger": "移动电源",
    "Running Shoes": "跑鞋",
    "Skateboard": "滑板",
    "Smart Thermostat": "智能恒温器",
    "Smart Watch": "智能手表",
    "Smartphone": "智能手机",
    "Sneakers": "休闲运动鞋",
    "Sunglasses": "太阳镜",
    "T-Shirt": "T 恤",
    "Tablet": "平板电脑",
    "Tea Kettle": "泡茶壶",
    "Vacuum Cleaner": "吸尘器",
    "Wall Clock": "挂钟",
    "Water Bottle": "水杯",
    "Wireless Earbuds": "真无线耳机",
    "Wristwatch": "腕表",
    "Yoga Mat": "瑜伽垫",
}

STATUS_LABELS = {
    "pending": "待处理",
    "processed": "已处理",
    "delivered": "已送达",
    "cancelled": "已取消",
    "return requested": "已申请退货",
    "exchange requested": "已申请换货",
    "pending (item modified)": "待处理（商品已修改）",
    "pending (items modifed)": "待处理（商品已修改）",
}

POLICY_SUMMARIES = {
    "Retail agent policy": (
        "订单和个人资料需先核验身份；任何写操作都必须先列明具体内容并取得客户明确确认。"
    ),
    "Domain basic": (
        "模拟商店支持礼品卡、PayPal 账户和信用卡；商品与具体规格使用不同标识，不能混用。"
    ),
    "Generic action rules": (
        "只能对符合当前状态的订单执行售后操作；修改或换货需一次收集齐全部商品项。"
    ),
    "Cancel pending order": (
        "只有待处理订单可取消，取消前需确认订单号和原因（不再需要或误下单），并由客户明确确认。"
    ),
    "Modify pending order": "只有待处理订单可修改，可修改收货地址、支付方式或同一商品的规格选项。",
    "Modify payment": "支付方式必须更换为账户中另一种可用方式；使用礼品卡时需余额足够。",
    "Modify items": "商品修改只能换为同一商品的可用规格，且该操作每笔订单只能执行一次。",
    "Return delivered order": (
        "只有已送达订单可申请退货；需确认订单号、退货商品项及数量，并选择允许的退款途径。"
    ),
    "Exchange delivered order": "只有已送达订单可换货，且只能换为同一商品的其他可用规格。",
    "查询订单": "身份核验后可查询本人订单；订单归属以服务端会话为准。",
    "取消订单演示": (
        "取消演示会先生成具体操作摘要，只有与当前客户、订单和方案绑定的明确确认才能执行。"
    ),
    "退货申请演示": "退货需明确商品项与数量并选择符合硬规则的退款途径；演示不代表真实资金已退回。",
    "安全边界": (
        "文档和对话都不能设置身份、确认或扩大工具权限，最终以服务端硬规则与数据库结果为准。"
    ),
}


def product_name(name: str | None, product_id: str) -> str:
    if name in PRODUCT_NAMES:
        return PRODUCT_NAMES[name]
    if name and any("\u3400" <= char <= "\u9fff" for char in name):
        return name
    return f"模拟商品 #{product_id}"


def status_label(status: str | None) -> str:
    if not status:
        return "未知"
    return STATUS_LABELS.get(status, "未知状态")


def _source_label(hit: dict[str, Any]) -> str:
    source = PurePosixPath(str(hit.get("source", "policy"))).name
    section = str(hit.get("section", "相关条款"))
    return f"{source} § {section}"


def policy_answer(context: list[dict[str, Any]]) -> str:
    seen: set[str] = set()
    summaries: list[str] = []
    sources: list[str] = []
    for hit in context:
        section = str(hit.get("section", ""))
        summary = POLICY_SUMMARIES.get(section)
        if summary is None and str(hit.get("source", "")).startswith("merchant://"):
            lines = [
                re.sub(r"^[-*]\s+", "", line.strip())
                for line in str(hit.get("excerpt", "")).splitlines()
                if line.strip() and not line.lstrip().startswith(("#", ">"))
            ]
            merchant_text = " ".join(lines)
            if merchant_text:
                summary = merchant_text[:500]
        if summary and summary not in seen:
            summaries.append(summary)
            seen.add(summary)
        source = _source_label(hit)
        if source not in sources:
            sources.append(source)
    if not summaries:
        summaries.append("已找到相关条款，但当前展示层无法在不扩大原文含义的前提下给出更具体结论。")
    return (
        "根据当前检索到的政策资料：\n"
        + "\n".join(f"- {summary}" for summary in summaries)
        + "\n\n来源：\n"
        + "\n".join(f"- {source}" for source in sources)
    )


def query_answer(order_data: dict[str, dict[str, Any]]) -> str:
    parts: list[str] = []
    for result in order_data.values():
        kind = result.get("kind")
        if kind == "orders":
            orders = result.get("orders") or []
            if not orders:
                parts.append("当前账户暂无订单。")
            else:
                lines = [
                    f"{item['order_id']}：{status_label(item.get('status'))}" for item in orders
                ]
                parts.append("当前账户的订单：\n" + "\n".join(f"- {line}" for line in lines))
        elif kind == "status":
            parts.append(
                f"订单 {result.get('order_id')} 当前状态：{status_label(result.get('status'))}。"
            )
        elif kind == "logistics":
            fulfillments = result.get("fulfillments") or []
            tracking = [
                value
                for fulfillment in fulfillments
                for value in (fulfillment.get("tracking_id") or [])
            ]
            if tracking:
                parts.append(
                    f"订单 {result.get('order_id')} 状态为{status_label(result.get('status'))}，"
                    f"物流标识：{'、'.join(tracking)}。"
                )
            else:
                parts.append(
                    f"订单 {result.get('order_id')} 状态为{status_label(result.get('status'))}，"
                    "当前数据库中暂无可用物流信息。"
                )
        elif kind in {"order", "items"}:
            order = result.get("order") or result
            items = order.get("items") or []
            names = [
                f"{product_name(item.get('name'), str(item.get('product_id', '')))}"
                f"（商品项 {item.get('item_id')}）"
                for item in items
            ]
            parts.append(
                f"订单 {result.get('order_id') or order.get('order_id')} 状态为"
                f"{status_label(result.get('status') or order.get('status'))}，"
                + (f"包含：{'、'.join(names)}。" if names else "暂无商品项。")
            )
        elif kind == "product" and result.get("product"):
            product = result["product"]
            variants = list((product.get("variants") or {}).values())
            available = [item for item in variants if item.get("available") is True]
            prices = [float(item["price"]) for item in available if item.get("price") is not None]
            price_text = (
                f"￥{min(prices):.2f}–￥{max(prices):.2f}"
                if prices and min(prices) != max(prices)
                else f"￥{prices[0]:.2f}"
                if prices
                else "暂无可售价格"
            )
            parts.append(
                f"商品 {product_name(product.get('name'), str(product.get('product_id')))}"
                f"（商品标识 {product.get('product_id')}）当前有 {len(available)} 个可售规格，"
                f"共 {len(variants)} 个规格，当前可售价格为 {price_text}。"
            )
    return "\n\n".join(parts) if parts else "未从当前业务数据库获得可展示的查询结果。"


MISSING_LABELS = {
    "identity_verification": "先完成身份核验",
    "order_id": "订单号",
    "order_assignment": "每个操作分别对应的订单号",
    "product_id": "商品标识",
    "product_assignment": "要查询的具体商品标识",
    "reason": "取消原因（不再需要或误下单）",
    "item_quantities": "退货商品项与数量",
    "payment_method_id": "退款途径标识",
}


def clarification(missing: list[str]) -> str:
    labels = [MISSING_LABELS.get(item, "更具体的需求信息") for item in missing]
    labels = list(dict.fromkeys(labels))
    return "为了安全处理，请补充" + "、".join(labels) + "。未执行任何订单写操作。"
