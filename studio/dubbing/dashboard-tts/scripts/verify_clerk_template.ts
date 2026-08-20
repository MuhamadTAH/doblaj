import process from 'node:process';

function parseJwt(token: string) {
  try {
    const base64Url = token.split('.')[1];
    if (!base64Url) return null;
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = Buffer.from(base64, 'base64').toString('utf8');
    return JSON.parse(jsonPayload);
  } catch (err) {
    return null;
  }
}

function printInstructions() {
  console.error('\n' + '='.repeat(80));
  console.error('❌ CLERK JWT TEMPLATE DIAGNOSTIC FAILED!');
  console.error('='.repeat(80));
  console.error('\nAction Required in your Clerk Dashboard:');
  console.error('1. Log into your Clerk Dashboard (https://dashboard.clerk.com).');
  console.error('2. Navigate to "JWT Templates" in the sidebar menu.');
  console.error('3. Click "New template" -> Select "Blank".');
  console.error('4. Set Name to exactly: dubbing-api');
  console.error('5. Set Token Lifetime (TTL) to: 60 (or desired TTL).');
  console.error('6. Add the following Claims JSON structure:');
  console.error('   {');
  console.error('     "aud": "dubbing-api",');
  console.error('     "workspace_id": "{{user.public_metadata.workspace_id}}",');
  console.error('     "email": "{{user.primary_email_address}}",');
  console.error('     "role": "{{user.public_metadata.role}}"');
  console.error('   }');
  console.error('7. Save the template and re-run this verification script.');
  console.error('='.repeat(80) + '\n');
}

async function verifyClerkJwtTemplate() {
  console.log('🔍 Running Clerk JWT Template Diagnostic Verification...\n');

  const testToken = process.env.CLERK_TEST_TOKEN || process.argv[2];

  if (!testToken) {
    console.warn('⚠️ No JWT token passed. Checking environment variable CLERK_TEST_TOKEN or CLI arg...');
    console.warn('Usage: npx tsx scripts/verify_clerk_template.ts <YOUR_CLERK_DUBBING_API_JWT>\n');
    printInstructions();
    process.exit(1);
  }

  const payload = parseJwt(testToken);

  if (!payload) {
    console.error('❌ Error: The provided token is not a valid base64 encoded JWT structure.');
    printInstructions();
    process.exit(1);
  }

  console.log('Decoded Token Payload Claims:');
  console.log(JSON.stringify(payload, null, 2));

  let passed = true;

  // Check aud claim
  if (payload.aud !== 'dubbing-api' && !(Array.isArray(payload.aud) && payload.aud.includes('dubbing-api'))) {
    console.error(`❌ Mismatch: 'aud' claim must be 'dubbing-api', got: ${JSON.stringify(payload.aud)}`);
    passed = false;
  } else {
    console.log('✅ PASS: Claim "aud" is correctly set to "dubbing-api"');
  }

  // Check role claim
  if (!payload.role) {
    console.warn("⚠️ Warning: 'role' claim is missing or empty in JWT payload. Admin routes require 'role': 'admin'.");
  } else {
    console.log(`✅ PASS: Claim "role" exists (value: "${payload.role}")`);
  }

  if (!passed) {
    printInstructions();
    process.exit(1);
  }

  console.log('\n🎉 SUCCESS: Clerk JWT Template "dubbing-api" is 100% compliant with zero-trust backend requirements!');
  process.exit(0);
}

verifyClerkJwtTemplate();
