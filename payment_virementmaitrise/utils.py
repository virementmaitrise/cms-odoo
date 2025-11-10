def get_pis_app_id(provider_sudo):
    """ Return the publishable key for PIS Application.

    Note: This method serves as a hook for modules that would fully implement payment Connect.

    :param recordset provider_sudo: The provider on which the key should be read, as a sudoed
                                    `payment.provider` record.
    :return: The publishable PIS key
    :rtype: str
    """
    return provider_sudo.fintecture_pis_app_id


def get_pis_app_secret(provider_sudo):
    """ Return the application secret key for PIS Application.

    Note: This method serves as a hook for modules that would fully implement payment Connect.

    :param recordset provider_sudo: The provider on which the key should be read, as a sudoed
                                    `payment.provider` record.
    :return: The application PIS secret key
    :rtype: str
    """
    return provider_sudo.fintecture_pis_app_secret


def get_pis_private_key(provider_sudo):
    """ Return the private key for PIS Application.

    Note: This method serves as a hook for modules that would fully implement payment Connect.

    :param recordset provider_sudo: The provider on which the key should be read, as a sudoed
                                    `payment.provider` record.
    :returns: The private PIS key
    :rtype: binary file content
    """
    return provider_sudo.fintecture_pis_private_key_file

