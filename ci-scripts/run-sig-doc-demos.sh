#!/bin/bash

if [ ! -f duffy.session ]; then
echo "Retrieving an AWS instance"
set +x
duffy client \
 request-session \
 pool=metal-ec2-c5n-centos-10s-x86_64,quantity=1 > duffy.session
fi


set -x

ip=$(jq '.session.nodes[].data.provision.public_ipaddress' duffy.session)
ip=$(echo $ip | sed -e 's|"||g')
echo "IP address: $ip"
session_id=$(jq '.session.id' duffy.session)
session_id=$(echo $session_id | sed -e 's|"||g')
echo "Session: $session_id"

# Make sure libsepol is up to date
ssh -o StrictHostKeyChecking=no -i $PWD/automotive_sig.ssh root@$ip dnf upgrade -y libsepol

# shellcheck disable=SC2087 # CI_REPOSITORY_URL and CI_MERGE_REQUEST_REF_PATH need to be expanded before execution on AWS host
ssh \
    -o " UserKnownHostsFile=/dev/null" \
    -o "StrictHostKeyChecking no" \
    -o "IdentitiesOnly=yes" \
    -i automotive_sig.ssh \
    root@$ip << EOF
cat > run.sh << EO
set -x
mkdir -p /dev/shm/docs
cd /dev/shm/docs
dnf install -y git rpm-build make
rpm --import https://www.centos.org/keys/RPM-GPG-KEY-CentOS-SIG-Automotive
git clone ${CI_REPOSITORY_URL}
cd automotive-image-builder
git fetch origin ${CI_MERGE_REQUEST_REF_PATH}
git checkout FETCH_HEAD
git show -s
make rpm_dev
dnf --repofrompath autosd,"https://mirror.stream.centos.org/SIGs/10-stream/autosd/$(uname -m)/packages-main/" localinstall -y automotive-image-builder-*.noarch.rpm
curl -o test_all.sh \
  "https://gitlab.com/CentOS/automotive/sig-docs/-/raw/main/demos/test_all.sh?ref_type=heads"
# Better safe than sorry, ensure we don't install aib if we didn't manage before
sed -i -e 's|dnf install -y git osbuild-auto automotive-image-builder |dnf install -y git osbuild-auto |' test_all.sh
time bash test_all.sh
EO
bash run.sh
EOF

success=$?
echo $success

scp -r \
    -o " UserKnownHostsFile=/dev/null" \
    -o "StrictHostKeyChecking no" \
    -o "IdentitiesOnly=yes" \
    -i automotive_sig.ssh \
    root@$ip:/dev/shm/docs/automotive-image-builder/sig-docs/demos/logs/ .
echo $?

echo "Closing session: $session_id"
set +x
duffy client \
 retire-session $session_id
rm duffy.session

exit $success
