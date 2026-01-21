# Testing secure boot with Automotive Image Builder

This directory contains some (non-supported) example files of how you would
generate and enroll secureboot keys to use when testing secureboot with
AIB generated images.

**WARNING**: Signing files in a secure way for production use is
complicated and should be done by experts. The approach shown here is
simple, and not secure (for example, it stores unencrypted keys on
disk). It is not meant for production, but for development and
testing.

## Quickstart

If you just want to do some quick testing there is a pre-generated and
pre-enrolled set of keys in the `pregenerated` director. Read below to
understand how they were created and how to use them, but then you
don't have to run all the commands to generate and enroll keys. The
password for these files is `password`.

Note: The pre-enrolled key works in fedora, but for some reason not
with the EFI firmware in centos 10. You can use the EFI firmware
from on CS10:
https://gitlab.com/CentOS/automotive/src/automotive-image-builder/-/releases/1.1.3/downloads/OVMF_CODE.secboot.fd

**WARNING**: Never ever use these files in production, as the key is
public.

## Generating secureboot keys for testing

First, let's generate some random keys:
```
$ ./generate-sb-keys.sh secureboot-keys
Generating secureboot keys in secureboot-keys
Exporting (encrypted) PKCS#12 file with cert nickname test-key
Enter Export Password:
Verifying - Enter Export Password:
Keys generated under secureboot-keys
```

This generates the `secureboot-keys` directory that contains various
files.  Note that it asks for a password for the generated PKCS#12
file. This can optionally be supplied to the script from a file like
so:

```
$ ./generate-sb-keys.sh --password-file key.pw secureboot-keys
Generating secureboot keys in secureboot-keys
Exporting (encrypted) PKCS#12 file with cert nickname test-key
```

### Secureboot key files

These files are data for the three main secureboot databases:

- PK - Platform Key / “Root of trust"

  This is the main key that a vendor would pre-load into the
  car. Owning the PK lets you switch the firmware between Setup Mode
  (keys can be replaced freely) and User Mode (Secure Boot
  enforcement).

- KEK - Key Exchange Key

  Keys allowed to update the Secure Boot databases (db, dbx) once PK
  is enrolled.

- db - Allowed Image Database

  Certificates whose signatures are trusted to boot OS loaders and
  kernels. Only binaries signed by a key in db can execute when Secure
  Boot is on.

For each of these databases, we have:

- `$NAME.key`

  Private RSA key used to sign updates or EFI binaries (keep secret).

- `$NAME.crt`

   X.509 certificate (PEM) matching the private key. Human-readable,
   good for tools like openssl and sbsign.

- `$NAME.cer`

  Same certificate in DER binary format. This is what UEFI firmware UI
  expects when you “Enroll … using file”.

- `$NAME.esl`

  EFI Signature List, the basic format the firmware understands when in Setup Mode (no PK yet).
  On a booted system You can install an ESL file with:
  ```
  sudo efi-updatevar -f PK.esl PK
  ```

- $NAME.auth — Time-based authenticated update

  An ESL wrapped and signed so the firmware can verify it was authorized.
  These are used after the PK is installed (User Mode). For example:
  ```
  efi-updatevar -f KEK.auth KEK
  efi-updatevar -f db.auth db
  ```

And additionally we have:
- GUID.txt

  Random UUID used when generating the ESL/Auth files (UEFI uses a
  GUID to identify the signature list owner).

- db.p12

  A PKCS#12 file that combines both db.key and db.crt in one, which
  can be used by pesign to sign EFI files.  This file is encrypted and
  the password has to be supplied when its used.

## Enrolling the keys

In a real machine the EFI keys are stored in the EFI variables in
firmware. When the system is in "setup mode" the EFI secureboot
variables can be set freely. But when a PK key is loaded it turns into
"user mode" and the other variables can only be set if they are signed
by the PK. Also, the system will only boot EFI firmware files
containing trusted signatures.

Qemu has two approaches to supporting EFI variables, which are used to
store the secureboot key. Newer versions of qemu support the qemuvars
device which can initialize the EFI variables from a json file. Such
a file can be used with something like:
```
$ air --efi-vars=efivars.json image.qcow2
```

To enroll, a private key into such a json file, use the virt-fw-vars tool:
```
$ virt-fw-vars --set-pk $(cat GUID.txt) PK.cer --add-kek $(cat GUID.txt) KEK.cer --add-db-cert $(cat GUID.txt) db.cer --output-json efivars.json
```

For older versions of qemu, the EFI variables is stored in a binary file
that is used as the nvram content directly. Such a file, which can be specified
in `air` with the `--secureboot-vars` option.

To enroll the keys we boot an image with an empty variable file, and
enroll the keys. This will update the file which we can then later
reuse to boot any image, knowing that it will now only boot EFI files
signed by the PK.

To do this, build and run the `enroll.aib.yml` image which embeds the keys that
where generated above (in the `secureboot-keys` directory.
```
$ aib-dev build --distro autosd10-latest-sig enroll.aib.yml enroll.img
$ air --secureboot-vars=secboot_vars.fd --secureboot-writeable enroll.img
```

In this VM, log in as root and run `enroll-keys.sh`. Then save the
generated `secboot_vars.fd` for later use (with --secureboot).

## Booting secureboot signed images

If you have an image where the EFI files are signed with the
secureboot keys you can use the `efivars.json` (using `--efi-vars`) or
`secboot_vars.fd` (using `--secboot-vars`) file generated above by to
`air`. This will fail to boot a non-signed or incorrectly signed
image.

## Signing EFI files

The "pesign" program can be used to sign EFI files. It is somewhat
hard to use, so to simplify this example there is a container image
with a signing script in the `signer` subdirectory. Build it like:

```
$ podman build -t efi-signer signer
```

Then, given an EFI file (example.efi) and the keys generated above in
`secureboot-keys` you can sign it like so:

```
$ podman run --rm -ti -v .:/work efi-signer --certificates secureboot-keys/db.p12  example.efi
Importing DB keys into pesign nss database
Enter password for PKCS12 file:
Signing example.efi with cert 'test-key'
```

If the password is in a file that can be supplied with `--password-file FILE`.
The signing script accepts multiple files, and all will be signed.
