from http import HTTPStatus
from typing import Any, Optional, Union

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.adc_69e1e87197b5f31c80403a3913468_body import Adc69E1E87197B5F31C80403A3913468Body
from ...models.response_error import ResponseError
from ...models.response_success import ResponseSuccess
from ...types import Response


def _get_kwargs(
    *,
    body: Adc69E1E87197B5F31C80403A3913468Body,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/fb/subscriber/setCustomFieldByName",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Union[ResponseError, ResponseSuccess]]:
    if response.status_code == 200:
        response_200 = ResponseSuccess.from_dict(response.json())

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
) -> Response[Union[ResponseError, ResponseSuccess]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: Adc69E1E87197B5F31C80403A3913468Body,
) -> Response[Union[ResponseError, ResponseSuccess]]:
    """***Limit:*** 10 queries per second

    Args:
        body (Adc69E1E87197B5F31C80403A3913468Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[ResponseError, ResponseSuccess]]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: Adc69E1E87197B5F31C80403A3913468Body,
) -> Optional[Union[ResponseError, ResponseSuccess]]:
    """***Limit:*** 10 queries per second

    Args:
        body (Adc69E1E87197B5F31C80403A3913468Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[ResponseError, ResponseSuccess]
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: Adc69E1E87197B5F31C80403A3913468Body,
) -> Response[Union[ResponseError, ResponseSuccess]]:
    """***Limit:*** 10 queries per second

    Args:
        body (Adc69E1E87197B5F31C80403A3913468Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[ResponseError, ResponseSuccess]]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: Adc69E1E87197B5F31C80403A3913468Body,
) -> Optional[Union[ResponseError, ResponseSuccess]]:
    """***Limit:*** 10 queries per second

    Args:
        body (Adc69E1E87197B5F31C80403A3913468Body):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[ResponseError, ResponseSuccess]
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed
