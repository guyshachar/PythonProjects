from collections.abc import Mapping
from typing import Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="F42Eb3580F33178Fdf9D87F0C778F86EBody")


@_attrs_define
class F42Eb3580F33178Fdf9D87F0C778F86EBody:
    """
    Attributes:
        first_name (Union[Unset, str]): First Name
        last_name (Union[Unset, str]): Last Name
        phone (Union[Unset, str]): Phone Number is required if Email and Whatsapp Phone properties are empty
        whatsapp_phone (Union[Unset, str]): Whatsapp Phone Number is required if Email and Phone Number properties are
            empty
        email (Union[Unset, str]): Email is required if Phone Number and Whatsapp Phone properties are empty
        gender (Union[Unset, str]): Gender
        has_opt_in_sms (Union[Unset, bool]): Has opt-in SMS is required if property Phone Number is not empty
        has_opt_in_email (Union[Unset, bool]): Has opt-in Email is required if property Email is not empty
        consent_phrase (Union[Unset, str]): Consent phrase is required if property `has_opt_in_sms` equal true
    """

    first_name: Union[Unset, str] = UNSET
    last_name: Union[Unset, str] = UNSET
    phone: Union[Unset, str] = UNSET
    whatsapp_phone: Union[Unset, str] = UNSET
    email: Union[Unset, str] = UNSET
    gender: Union[Unset, str] = UNSET
    has_opt_in_sms: Union[Unset, bool] = UNSET
    has_opt_in_email: Union[Unset, bool] = UNSET
    consent_phrase: Union[Unset, str] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        first_name = self.first_name

        last_name = self.last_name

        phone = self.phone

        whatsapp_phone = self.whatsapp_phone

        email = self.email

        gender = self.gender

        has_opt_in_sms = self.has_opt_in_sms

        has_opt_in_email = self.has_opt_in_email

        consent_phrase = self.consent_phrase

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if first_name is not UNSET:
            field_dict["first_name"] = first_name
        if last_name is not UNSET:
            field_dict["last_name"] = last_name
        if phone is not UNSET:
            field_dict["phone"] = phone
        if whatsapp_phone is not UNSET:
            field_dict["whatsapp_phone"] = whatsapp_phone
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
        first_name = d.pop("first_name", UNSET)

        last_name = d.pop("last_name", UNSET)

        phone = d.pop("phone", UNSET)

        whatsapp_phone = d.pop("whatsapp_phone", UNSET)

        email = d.pop("email", UNSET)

        gender = d.pop("gender", UNSET)

        has_opt_in_sms = d.pop("has_opt_in_sms", UNSET)

        has_opt_in_email = d.pop("has_opt_in_email", UNSET)

        consent_phrase = d.pop("consent_phrase", UNSET)

        f42_eb_3580f33178_fdf_9d87f0c778f86e_body = cls(
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            whatsapp_phone=whatsapp_phone,
            email=email,
            gender=gender,
            has_opt_in_sms=has_opt_in_sms,
            has_opt_in_email=has_opt_in_email,
            consent_phrase=consent_phrase,
        )

        f42_eb_3580f33178_fdf_9d87f0c778f86e_body.additional_properties = d
        return f42_eb_3580f33178_fdf_9d87f0c778f86e_body

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
