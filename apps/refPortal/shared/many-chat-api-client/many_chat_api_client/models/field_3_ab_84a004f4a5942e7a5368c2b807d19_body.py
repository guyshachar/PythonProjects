from collections.abc import Mapping
from typing import Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="Field3Ab84A004F4A5942E7A5368C2B807D19Body")


@_attrs_define
class Field3Ab84A004F4A5942E7A5368C2B807D19Body:
    """
    Attributes:
        subscriber_id (int):
        first_name (Union[Unset, str]): First Name
        last_name (Union[Unset, str]): Last Name
        phone (Union[Unset, str]): Phone Number
        email (Union[Unset, str]): Email
        gender (Union[Unset, str]): Gender
        has_opt_in_sms (Union[Unset, bool]): Has opt-in SMS is required if property Phone Number is not empty
        has_opt_in_email (Union[Unset, bool]): Has opt-in Email is required if property Email is not empty
        consent_phrase (Union[Unset, str]): Consent phrase is required if property Has Opt In SMS equal true
    """

    subscriber_id: int
    first_name: Union[Unset, str] = UNSET
    last_name: Union[Unset, str] = UNSET
    phone: Union[Unset, str] = UNSET
    email: Union[Unset, str] = UNSET
    gender: Union[Unset, str] = UNSET
    has_opt_in_sms: Union[Unset, bool] = UNSET
    has_opt_in_email: Union[Unset, bool] = UNSET
    consent_phrase: Union[Unset, str] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        subscriber_id = self.subscriber_id

        first_name = self.first_name

        last_name = self.last_name

        phone = self.phone

        email = self.email

        gender = self.gender

        has_opt_in_sms = self.has_opt_in_sms

        has_opt_in_email = self.has_opt_in_email

        consent_phrase = self.consent_phrase

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "subscriber_id": subscriber_id,
            }
        )
        if first_name is not UNSET:
            field_dict["first_name"] = first_name
        if last_name is not UNSET:
            field_dict["last_name"] = last_name
        if phone is not UNSET:
            field_dict["phone"] = phone
        if email is not UNSET:
            field_dict["email"] = email
        if gender is not UNSET:
            field_dict["gender"] = gender
        if has_opt_in_sms is not UNSET:
            field_dict["has_opt_in_sms"] = has_opt_in_sms
        if has_opt_in_email is not UNSET:
            field_dict["has_opt_in_email"] = has_opt_in_email
        if consent_phrase is not UNSET:
            field_dict["consent_phrase"] = consent_phrase

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        subscriber_id = d.pop("subscriber_id")

        first_name = d.pop("first_name", UNSET)

        last_name = d.pop("last_name", UNSET)

        phone = d.pop("phone", UNSET)

        email = d.pop("email", UNSET)

        gender = d.pop("gender", UNSET)

        has_opt_in_sms = d.pop("has_opt_in_sms", UNSET)

        has_opt_in_email = d.pop("has_opt_in_email", UNSET)

        consent_phrase = d.pop("consent_phrase", UNSET)

        field_3_ab_84a004f4a5942e7a5368c2b807d19_body = cls(
            subscriber_id=subscriber_id,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
            gender=gender,
            has_opt_in_sms=has_opt_in_sms,
            has_opt_in_email=has_opt_in_email,
            consent_phrase=consent_phrase,
        )

        field_3_ab_84a004f4a5942e7a5368c2b807d19_body.additional_properties = d
        return field_3_ab_84a004f4a5942e7a5368c2b807d19_body

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
