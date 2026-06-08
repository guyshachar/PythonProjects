from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.field_782_cc_8_abe_7878_dc_73026b6_bef_44f14b2_response_200 import (
    Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200,
)
from ...models.response_error_with_code import ResponseErrorWithCode
from ...types import UNSET, Response


def _get_kwargs(
    *,
    user_ref: int,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    params["user_ref"] = user_ref

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/fb/subscriber/getInfoByUserRef",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Union[Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200, ResponseErrorWithCode]]:
    if response.status_code == 200:
        response_200 = Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200.from_dict(response.json())

        return response_200
    if response.status_code == 400:
        response_400 = ResponseErrorWithCode.from_dict(response.json())

        return response_400
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[Union[Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200, ResponseErrorWithCode]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    user_ref: int,
) -> Response[Union[Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200, ResponseErrorWithCode]]:
    """
    Args:
        user_ref (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200, ResponseErrorWithCode]]
    """

    kwargs = _get_kwargs(
        user_ref=user_ref,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    user_ref: int,
) -> Optional[Union[Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200, ResponseErrorWithCode]]:
    """
    Args:
        user_ref (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200, ResponseErrorWithCode]
    """

    return sync_detailed(
        client=client,
        user_ref=user_ref,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    user_ref: int,
) -> Response[Union[Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200, ResponseErrorWithCode]]:
    """
    Args:
        user_ref (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200, ResponseErrorWithCode]]
    """

    kwargs = _get_kwargs(
        user_ref=user_ref,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    user_ref: int,
) -> Optional[Union[Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200, ResponseErrorWithCode]]:
    """
    Args:
        user_ref (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[Field782Cc8Abe7878Dc73026B6Bef44F14B2Response200, ResponseErrorWithCode]
    """

    return (
        await asyncio_detailed(
            client=client,
            user_ref=user_ref,
        )
    ).parsed
