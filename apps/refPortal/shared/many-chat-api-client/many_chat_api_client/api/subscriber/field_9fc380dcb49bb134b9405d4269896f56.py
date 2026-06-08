from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.field_9_fc_380_dcb_49_bb_134b9405d4269896f56_response_200 import (
    Field9Fc380Dcb49Bb134B9405D4269896F56Response200,
)
from ...models.response_error import ResponseError
from ...types import UNSET, Response


def _get_kwargs(
    *,
    field_id: int,
    field_value: str,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    params["field_id"] = field_id

    params["field_value"] = field_value

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/fb/subscriber/findByCustomField",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Union[Field9Fc380Dcb49Bb134B9405D4269896F56Response200, ResponseError]]:
    if response.status_code == 200:
        response_200 = Field9Fc380Dcb49Bb134B9405D4269896F56Response200.from_dict(response.json())

        return response_200
    if response.status_code == 400:
        response_400 = ResponseError.from_dict(response.json())

        return response_400
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[Union[Field9Fc380Dcb49Bb134B9405D4269896F56Response200, ResponseError]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    field_id: int,
    field_value: str,
) -> Response[Union[Field9Fc380Dcb49Bb134B9405D4269896F56Response200, ResponseError]]:
    """***Limit:*** 10 queries per second.<br>
    This API method only works with Text and Number types of Custom User Fields.<br>
    Results are sorted by last Custom User Field value update for a specific user.<br>
    List is limited by 100 elements.

    Args:
        field_id (int):
        field_value (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[Field9Fc380Dcb49Bb134B9405D4269896F56Response200, ResponseError]]
    """

    kwargs = _get_kwargs(
        field_id=field_id,
        field_value=field_value,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    field_id: int,
    field_value: str,
) -> Optional[Union[Field9Fc380Dcb49Bb134B9405D4269896F56Response200, ResponseError]]:
    """***Limit:*** 10 queries per second.<br>
    This API method only works with Text and Number types of Custom User Fields.<br>
    Results are sorted by last Custom User Field value update for a specific user.<br>
    List is limited by 100 elements.

    Args:
        field_id (int):
        field_value (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[Field9Fc380Dcb49Bb134B9405D4269896F56Response200, ResponseError]
    """

    return sync_detailed(
        client=client,
        field_id=field_id,
        field_value=field_value,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    field_id: int,
    field_value: str,
) -> Response[Union[Field9Fc380Dcb49Bb134B9405D4269896F56Response200, ResponseError]]:
    """***Limit:*** 10 queries per second.<br>
    This API method only works with Text and Number types of Custom User Fields.<br>
    Results are sorted by last Custom User Field value update for a specific user.<br>
    List is limited by 100 elements.

    Args:
        field_id (int):
        field_value (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[Field9Fc380Dcb49Bb134B9405D4269896F56Response200, ResponseError]]
    """

    kwargs = _get_kwargs(
        field_id=field_id,
        field_value=field_value,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    field_id: int,
    field_value: str,
) -> Optional[Union[Field9Fc380Dcb49Bb134B9405D4269896F56Response200, ResponseError]]:
    """***Limit:*** 10 queries per second.<br>
    This API method only works with Text and Number types of Custom User Fields.<br>
    Results are sorted by last Custom User Field value update for a specific user.<br>
    List is limited by 100 elements.

    Args:
        field_id (int):
        field_value (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[Field9Fc380Dcb49Bb134B9405D4269896F56Response200, ResponseError]
    """

    return (
        await asyncio_detailed(
            client=client,
            field_id=field_id,
            field_value=field_value,
        )
    ).parsed
