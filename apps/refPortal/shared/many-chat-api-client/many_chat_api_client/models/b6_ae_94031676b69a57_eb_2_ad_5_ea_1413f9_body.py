from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.b6_ae_94031676b69a57_eb_2_ad_5_ea_1413f9_body_data import B6Ae94031676B69A57Eb2Ad5Ea1413F9BodyData


T = TypeVar("T", bound="B6Ae94031676B69A57Eb2Ad5Ea1413F9Body")


@_attrs_define
class B6Ae94031676B69A57Eb2Ad5Ea1413F9Body:
    """
    Attributes:
        subscriber_id (int):
        data (B6Ae94031676B69A57Eb2Ad5Ea1413F9BodyData):
        message_tag (Union[Unset, str]):  Example: ACCOUNT_UPDATE.
        otn_topic_name (Union[Unset, str]):  Example: Сhannel news.
    """

    subscriber_id: int
    data: "B6Ae94031676B69A57Eb2Ad5Ea1413F9BodyData"
    message_tag: Union[Unset, str] = UNSET
    otn_topic_name: Union[Unset, str] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        subscriber_id = self.subscriber_id

        data = self.data.to_dict()

        message_tag = self.message_tag

        otn_topic_name = self.otn_topic_name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "subscriber_id": subscriber_id,
                "data": data,
            }
        )
        if message_tag is not UNSET:
            field_dict["message_tag"] = message_tag
        if otn_topic_name is not UNSET:
            field_dict["otn_topic_name"] = otn_topic_name

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.b6_ae_94031676b69a57_eb_2_ad_5_ea_1413f9_body_data import B6Ae94031676B69A57Eb2Ad5Ea1413F9BodyData

        d = dict(src_dict)
        subscriber_id = d.pop("subscriber_id")

        data = B6Ae94031676B69A57Eb2Ad5Ea1413F9BodyData.from_dict(d.pop("data"))

        message_tag = d.pop("message_tag", UNSET)

        otn_topic_name = d.pop("otn_topic_name", UNSET)

        b6_ae_94031676b69a57_eb_2_ad_5_ea_1413f9_body = cls(
            subscriber_id=subscriber_id,
            data=data,
            message_tag=message_tag,
            otn_topic_name=otn_topic_name,
        )

        b6_ae_94031676b69a57_eb_2_ad_5_ea_1413f9_body.additional_properties = d
        return b6_ae_94031676b69a57_eb_2_ad_5_ea_1413f9_body

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
